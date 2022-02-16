#!/usr/bin/env python3
import argparse
import base64
import contextlib
import io
import json
import logging
import os
import sys
import tarfile
import time

import docker

from ..common import PatchStatus
from ..database import Db


l = logging.getLogger("patchbot")

def bin_diff(byte_arr1, byte_arr2):
    byte_diff = 0
    for (x,y) in zip(byte_arr1, byte_arr2):
        if x != y:
            byte_diff += 1

    return byte_diff + abs(len(byte_arr1) - len(byte_arr2))

# Need this for ooows to set the device parameter to /dev/kvm
DOCKER_DEVICE_OPTION = [os.environ["DOCKER_DEVICE_OPTION"]] if "DOCKER_DEVICE_OPTION" in os.environ else []

@contextlib.contextmanager
def launch_container(client, docker_api, image, network_name=None, pull_latest=False, command=None, mem_limit=None, mem_reservation=None, environment=None, hostname=None):
    if mem_limit is None: mem_limit = '512M'
    if mem_reservation is None: mem_reservation = '512M'
    l.debug(f"Going to run image {image}")
    if pull_latest:
        l.info(f"Getting the latest {image}")
        client.images.pull(image)

    # INSANE HACK TO SUPPORT A CHALLENGE, WHY DO WE DO THIS TO OURSELVES AT THE LAST MINUTE EVERY TIME
    security_opt = []
    if os.path.exists("/etc/default.json"):
        with open("/etc/default.json", 'r') as f:
            security_opt = [f"seccomp={f.read()}"]
    try:
        container = client.containers.run(image, command=command,
                                          network=network_name,
                                          detach=True,
                                          mem_limit=mem_limit,
                                          mem_reservation=mem_reservation,
                                          environment=environment,
                                          hostname=hostname,
                                          devices=DOCKER_DEVICE_OPTION,
                                          security_opt=security_opt,
        )
    except Exception:
        l.exception(f"Error running {image}")
        return None, None

    l.debug(f"container {container.name} (image {image}) launched")

    # Give it some time to come up [ TODO: necessary? wait for endpoint IP/port? ]
    time.sleep(2)

    try:
        yield container
    finally:
        l.debug(f"stopping container {container.name} {image} ")
        l.info(f"container {container.name} {image} output {container.logs(stderr=True)}")
        container.reload()
        l.debug(f"container {container.name} {image} status {container.status}")
        if container.status != 'exited':
            try:
                # TODO: why does this happen?
                l.debug(f"status != exited after container.reload(), killing container {container.name} {image}")
                container.kill()
            except Exception:
                l.info(f"exception when killing container {container.name} {image}, likely nothing, so continuing.")
        try:
            container.remove()
        except Exception:
            l.exception(f"error removing container {container.name} image {image}, this is likely bad but going to carry on.")

def get_ip(docker_api, container_name):
    result = docker_api.inspect_container(container_name)
    if not result:
        l.critical(f"Unable to inspect {container_name} {result}")
        return None

    networks = result['NetworkSettings']['Networks']
    assert len(networks) == 1

    ip = list(networks.values())[0]['IPAddress']
    l.debug(f"{container_name} has ip address {ip}")
    return ip

def get_docker_network(client, service_id):
    network_name = f"no-inet-service-{service_id}"
    try:
        l.debug(f"Trying to get the network {network_name}")
        client.networks.get(network_id=network_name)
    except Exception:
        l.info(f"Network {network_name} doesn't exist, let's create it")
        ipam_pool = docker.types.IPAMPool(
            subnet=f"10.231.{service_id}.0/24",
        )
        ipam_config = docker.types.IPAMConfig(
            pool_configs=[ipam_pool]
        )
        client.networks.create(network_name, driver='bridge', internal=True, ipam=ipam_config)
    return network_name

def get_file_from_container_as_tar(container, file_location):
    bits, stat = container.get_archive(file_location)
    tar_archive = b""
    for b in bits:
        tar_archive += b

    return tarfile.TarFile(fileobj=io.BytesIO(tar_archive))

def drop_file_on_container(container, path_to_file, file_contents, mode, uid, gid):
    tarinfo = tarfile.TarInfo(name=path_to_file)
    tarinfo.mode = mode
    tarinfo.uid = uid
    tarinfo.gid = gid
    tarinfo.size = len(file_contents)

    pw_tarstream = io.BytesIO()
    pw_tar = tarfile.TarFile(fileobj=pw_tarstream, mode='w')
    pw_tar.addfile(tarinfo, io.BytesIO(file_contents))
    pw_tar.close()

    pw_tarstream.seek(0)

    l.info(f"dropping file {path_to_file} on container {container.name} with mode {oct(mode)} uid {uid} gid {gid}")
    result = container.put_archive('/', pw_tarstream)
    l.debug(f"put_archive result {result}")
    return result

def get_patch_byte_diff(container, docker_location_to_patch, new_file):

    l.info(f"Going to get the file {docker_location_to_patch}")
    archive = get_file_from_container_as_tar(container, docker_location_to_patch)
    l.info(f"got the following files {archive.getnames()}")
    assert len(archive.getmembers()) == 1

    base_to_patch = os.path.basename(docker_location_to_patch)
    current_file_info = archive.getmember(base_to_patch)
    assert current_file_info

    current_file = archive.extractfile(current_file_info)
    assert current_file

    bytes_diff = bin_diff(current_file.read(), new_file)
    return bytes_diff, current_file_info

def get_patch_tag(service_id, patch_id):
    return f"service-{service_id}-patch-{patch_id}"

def patch_file_and_tag(container, patch_tag, docker_location_to_patch, new_file, mode, uid, gid):
    result = drop_file_on_container(container, docker_location_to_patch, new_file, mode, uid, gid)
    if not result:
        l.error(f"Unable to create file {docker_location_to_patch}")
        return None

    result = container.commit(patch_tag, tag="latest")
    l.info(f"tagged the patched version as {patch_tag} result {result}")
    if not result:
        l.critical(f"unable to commit the tag {patch_tag} result {result}")
        return None

    return True

def deploy_container(client, docker_api, previous, target):
    l.info(f"deploying patched container to {target} from {previous}")

    result = docker_api.tag(previous, target)
    if not result:
        l.critical(f"Unable to tag {previous} to {target}")
        return None
    l.debug(f"docker_api.tag result: {result}")

    result = client.images.push(target)
    if not result:
        l.critical(f"Unable to push {target}")
        return None
    l.debug(f"client.images.push result: {result}")

    l.info(f"deploying {previous} to {target} was successful")
    return True

def get_public_metadata(container_output):
    """
    Return a string containing any public metadata from stdout from the logs of this container.
    """
    PREFIX=b'PUBLIC: '
    to_return = b""
    for line in container_output.splitlines():
        if line.startswith(PREFIX):
            to_return += line[len(PREFIX):]
            to_return += b"\n"
    if to_return == b"":
        return None
    else:
        return to_return.strip()

class dummy_context_mgr():
    def __enter__(self):
        return None
    def __exit__(self, exc_type, exc_value, traceback):
        return False

def test_remote_interactions(client, docker_api, container_to_test, remote_interaction_container_name, network_name, remote_interaction_scripts, service_port, check_timeout, team_id, service_id=None, registry=None, **kwargs):
    with dummy_context_mgr() as server_container:   # In 2020 we used this to spawn the game-server container for Yanick's rhg service
        prior_pull_latest = kwargs['pull_latest'] if 'pull_latest' in kwargs else None
        kwargs['pull_latest'] = False

        environment = {}
        hostname = None
        with launch_container(client, docker_api, container_to_test, network_name=network_name, environment=environment, hostname=hostname, **kwargs) as testing_container:
            kwargs['pull_latest'] = prior_pull_latest
            ip = get_ip(docker_api, testing_container.name)

            for script in remote_interaction_scripts:
                l.info(f"running remote interaction script {script} on {container_to_test} {ip}:{service_port}")
                with launch_container(client, docker_api, remote_interaction_container_name, network_name="host", command=[script, str(ip), str(service_port)], environment={'TEAM_ID': team_id}, **kwargs) as interaction_container:
                    try:
                        result = interaction_container.wait(timeout=check_timeout)
                        l.info(f"Result from running remote interaction script {result}")
                    except Exception:
                        l.info(f"Got a timeout on SLA check {sys.exc_info()[1]}.")
                        l.info(f"stdout from interaction_container {remote_interaction_container_name} {interaction_container.logs(stdout=True)}")
                        return PatchStatus.SLA_TIMEOUT, get_public_metadata(interaction_container.logs())

                    exit_code = result['StatusCode']
                    container_output = interaction_container.logs(stdout=True)
                    l.info(f"stdout from interaction_container {remote_interaction_container_name} {container_output}")
                    if exit_code != 0:
                        l.info(f"Failed SLA check with exit code {exit_code}")
                        return PatchStatus.SLA_FAIL, get_public_metadata(container_output)
                    l.debug(f"passed SLA check for script {script}")

    return True, None

def test_local_changes(client, docker_api, local_interaction_tag, local_interaction_container_name, docker_location_to_patch, new_file, new_file_mode, new_file_uid, new_file_gid, network_name, local_interaction_scripts, check_timeout, team_id, **kwargs):
    # If there are no local interaction scripts, then our job here is done
    l.info(f"Testing local interaction scripts for {local_interaction_tag} {local_interaction_container_name}")
    if len(local_interaction_scripts) == 0:
        l.warning(f"No local interaction scripts, behaving as if they succeeded.")
        return True, None

    l.debug(f"Going to run the original local container {local_interaction_container_name}")
    with launch_container(client, docker_api, local_interaction_container_name, network_name=network_name, **kwargs) as original_local_container:
    # need to patch the local interaction container
        result = patch_file_and_tag(original_local_container, local_interaction_tag, docker_location_to_patch, new_file, new_file_mode, new_file_uid, new_file_gid)
        if not result:
            l.error(f"unable to patch and tag local container")
            return None, None

    l.info(f"Created a patched version {local_interaction_tag} of the local container {local_interaction_container_name}.")
    # run each of the scripts
    for script in local_interaction_scripts:
        l.info(f"running local interaction script {script} on {local_interaction_tag}.")
        prior_pull_latest = kwargs['pull_latest'] if 'pull_latest' in kwargs else None
        kwargs['pull_latest'] = False
        with launch_container(client, docker_api, local_interaction_tag, network_name="host", command=[script], environment={'TEAM_ID': team_id}, **kwargs) as local_container:
            kwargs['pull_latest'] = prior_pull_latest
            try:
                result = local_container.wait(timeout=check_timeout)
                l.info(f"Result from running local interaction script {result}")
            except Exception:
                l.info(f"Got a timeout on SLA check {sys.exc_info()[1]}.")
                l.info(f"stdout from local_container {local_interaction_tag} {local_container.logs(stdout=True)}")
                return PatchStatus.SLA_TIMEOUT, get_public_metadata(local_container.logs())

            exit_code = result['StatusCode']
            container_output = local_container.logs(stdout=True)
            l.info(f"stdout from local_container {local_interaction_tag} {container_output}")
            if exit_code != 0:
                l.info(f"Failed SLA check with exit code {exit_code}")
                return PatchStatus.SLA_FAIL, get_public_metadata(container_output)
            l.debug(f"passed SLA check for script {script}")

    return True, None

def check_and_deploy_service(client, docker_api, container_name, deployed_container_name, remote_interaction_container_name, local_interaction_container_name, patch_id, service_id, service_port, remote_interaction_scripts, local_interaction_scripts, docker_location_to_patch, new_file, max_bytes, check_timeout, team_id=1, pull_latest=True, deploy_service=True, registry=None, **kwargs):
    network_name = get_docker_network(client, service_id)
    l.debug(f"Got network_name {network_name}")
    with launch_container(client, docker_api, container_name, network_name, pull_latest=pull_latest, **kwargs) as container:
        # Check the diff in bytes
        bytes_diff, current_file_info = get_patch_byte_diff(container, docker_location_to_patch, new_file)
        l.info(f"patched file resulted in {bytes_diff} with {max_bytes} total bytes to patch")
        if bytes_diff > max_bytes:
            l.info(f"Too many bytes diff")
            return PatchStatus.TOO_MANY_BYTES, f"Had {bytes_diff} difference, only {max_bytes} allowed"

        l.info(f"Going to create a patched version of the service.")

        patch_tag = get_patch_tag(service_id, patch_id)
        result = patch_file_and_tag(container, patch_tag, docker_location_to_patch, new_file, current_file_info.mode, current_file_info.uid, current_file_info.gid)
        if not result:
            l.error(f"unable to patch and tag")
            return None, None


    local_interaction_tag = f"{patch_tag}-local-interaction"
    l.info(f"Going to test local interactions for {local_interaction_tag}")
    result, metadata = test_local_changes(client, docker_api, local_interaction_tag, local_interaction_container_name, docker_location_to_patch, new_file, current_file_info.mode, current_file_info.uid, current_file_info.gid, network_name, local_interaction_scripts, check_timeout, team_id, pull_latest=pull_latest, **kwargs)
    if not result == True:
        return result, metadata

    # Test the patched service
    l.info(f"Going to test remote interactions for {patch_tag}")
    result, metadata = test_remote_interactions(client, docker_api, patch_tag, remote_interaction_container_name, network_name, remote_interaction_scripts, service_port, check_timeout, team_id=team_id, service_id=service_id, registry=registry, pull_latest=pull_latest, **kwargs)
    if not result == True:
        return result, metadata

    # Deploy the patched service
    if deploy_service:
        result = deploy_container(client, docker_api, patch_tag, deployed_container_name)
        if not result:
            l.critical("error deploying container")
            return None, None
    else:
        l.info(f"Skipping deploying the service because deploy_service is {deploy_service}")

    return PatchStatus.ACCEPTED, None

def get_service_docker_info(registry, service):
    return f"{registry}{service['service_docker']}", f"{registry}{service['interaction_docker']}", f"{registry}{service['local_interaction_docker']}"

def test_patch(patch_id, dbapi=None, the_db=None, registry=None, update_db=True, deploy_service=True, **kwargs):
    """
    Test the patch_id and use the given dbapi (which will be taken
    from DATABASE_API in the environment if not given), timeout if any
    check takes longer than check_timeout seconds. Registry will be used to push to.
    Use kwargs for launch_container arguments such as mem_limit and mem_reservation.
    """
    if not dbapi:
        if 'DATABASE_API' in os.environ:
            dbapi = os.environ['DATABASE_API']

    if dbapi and the_db:
        l.critical(f"cannot specify dbapi {dbapi} and the_db {the_db}")
        return

    if not registry:
        if not 'DOCKER_REGISTRY' in os.environ:
            l.critical(f"No registry given, can't do anything")
            return
        registry = os.environ['DOCKER_REGISTRY']

    if not registry.endswith("/"):
        l.warning(f"registry {registry} must end in slash, adding it for you.")
        registry += "/"

    if not the_db:
        if not dbapi:
            l.critical(f"No dbapi and no the_db given")
            return
        the_db = Db(dbapi)

    l.info(f"going to test patch id {patch_id} using {the_db} and registry {registry}")

    patch = the_db.patch(patch_id)
    service = the_db.service(patch['service_id'])

    client = docker.from_env()
    api = docker.APIClient()

    service_base_name, remote_interaction_name, local_interaction_name = get_service_docker_info(registry, service)

    to_deploy_name = f"{registry}{service['name']}-team-{patch['team_id']}:latest"

    remote_scripts = service['sla_scripts']

    check_timeout = service['check_timeout']

    local_interaction_scripts = service['local_interaction_scripts']

    patch_uploaded_file = base64.b64decode(patch['uploaded_file'])
    patch_hash = patch['uploaded_hash']


    l.debug(f"going to check {service['name']} id {service['id']} patch {patch['id']} base {service_base_name} deploying to {to_deploy_name} using remote {remote_interaction_name} local {local_interaction_name} on port {service['container_port']} remote scripts {remote_scripts} local scripts {local_interaction_scripts} location to patch {service['patchable_file_from_docker']} max byte changes {service['max_bytes']} check timeout {check_timeout} updated_db {update_db} deploy_service {deploy_service} patch_hash={patch_hash}")

    if update_db:
        the_db.set_patch_status(patch['id'], PatchStatus.TESTING_PATCH.name)

    result, metadata = check_and_deploy_service(client,
                                                api,
                                                container_name=service_base_name,
                                                deployed_container_name=to_deploy_name,
                                                remote_interaction_container_name=remote_interaction_name,
                                                local_interaction_container_name=local_interaction_name,
                                                patch_id=patch['id'],
                                                service_id=service['id'],
                                                service_port=service['container_port'],
                                                remote_interaction_scripts=remote_scripts,
                                                local_interaction_scripts=local_interaction_scripts,
                                                docker_location_to_patch=service['patchable_file_from_docker'],
                                                new_file=patch_uploaded_file,
                                                max_bytes=service['max_bytes'],
                                                check_timeout=check_timeout,
                                                pull_latest=True,
                                                deploy_service=deploy_service,
                                                team_id=patch['team_id'],
                                                registry=registry,
                                                **kwargs)

    l.info(f"got result {result} metadata {metadata}")

    if result == None:
        l.critical("Something went very wrong, not going to update the database for this one.")
        raise Exception(f"Unable to successfully test this patch {patch['id']}")

    if update_db:
        response = the_db.set_patch_status(patch['id'], result.name, public_metadata=metadata)
        l.info(f"response {response} from db.")
        if result == PatchStatus.ACCEPTED:
            team = the_db.team(patch['team_id'])
            team_name = json.dumps(team['name'])
            team_id = patch['team_id']
            service_name = json.dumps(service['name'])
            service_id = service['id']
            l.info(f"NEW ACCEPTED PATCH: patch_id={patch['id']} team_name={team_name} team_id={team_id} service_name={service_name} service_id={service_id} patch_hash={patch_hash}")

    else:
        l.info(f"Not updating the DB with the result of testing the patch")
    return True

def local_download_patch(args):
    dbapi = args.dbapi
    patch_id = args.patch_id

    the_db = Db(dbapi)
    l.debug(f"fetch patch {patch_id} from the db")
    patch = the_db.patch(patch_id)
    service = the_db.service(patch['service_id'])
    patch_uploaded_file = base64.b64decode(patch['uploaded_file'])

    file_name = f"service_{service['id']}_team_{patch['team_id']}_patch_{patch['id']}"

    path = os.path.join(args.download_dir, file_name)
    with open(path, "wb") as f:
        f.write(patch_uploaded_file)

    l.info(f"Saved patch {patch['id']} to {path}")

def update_patch_status(args):
    dbapi = args.dbapi
    patch_id = args.patch_id
    status = PatchStatus[args.status.upper()]
    metadata = args.metadata

    the_db = Db(dbapi)

    l.info(f"Updating patch {patch_id} from the db with status {status} and metadata {metadata}")
    patch = the_db.patch(patch_id)
    service = the_db.service(patch['service_id'])

    if not service['is_manual_patching']:
        l.error("I refuse to manually update the status of a service (%s) that is automatically patched.", service)
        sys.exit(-1)

    response = the_db.set_patch_status(patch['id'], status.name, public_metadata=metadata, private_metadata="Custom status set")
    l.info(f"Response from the db {response}")

def our_bin_diff(args):
    f1 = args.file_1
    f2 = args.file_2

    with open(f1, 'rb') as file_1:
        with open(f2, 'rb') as file_2:
            diff = bin_diff(file_1.read(), file_2.read())
            l.info(f"Diff between {f1} and {f2}: {diff}")

def warm_patchbot(args, the_db=None):
    registry = args.registry
    if 'DOCKER_REGISTRY' in os.environ:
        registry = os.environ['DOCKER_REGISTRY']

    dbapi = args.dbapi
    if 'DATABASE_API' in os.environ:
        dbapi = os.environ['DATABASE_API']
    if not the_db:
        the_db = Db(dbapi)

    client = docker.from_env()

    services = the_db.services()
    for service in services:
        if service['type'] != 'NORMAL':
            continue

        l.info(f"Going to warm the patchbot cache for service_id={service['id']} service_name={service['name']}")

        containers = get_service_docker_info(registry, service)
        for c in containers:
            l.debug(f"About to pull container={c} from registry={registry}")
            try:
                client.images.pull(c)
            except docker.errors.APIError as e:
                l.warning(f"Error pulling container={c} with error={e}")

def local_test_patch(args):
    l.setLevel(logging.DEBUG)

    l.debug(f"Going to test {args.patch_id} locally using database API {args.dbapi} and docker registry {args.registry}, without deploying the finished/patched service and without updating the database (mem_limit={args.mem_limit} mem_reservation={args.mem_reservation})")
    test_patch(args.patch_id, dbapi=args.dbapi, registry=args.registry, update_db=False, deploy_service=False,
            mem_limit=args.mem_limit, mem_reservation=args.mem_reservation)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="patchbot")
    parser.add_argument("--dbapi", default="http://master.admin.31337.ooo:30000", help="The location of the database API")
    parser.add_argument("--registry", default="registry.31337.ooo:6000/", help="The location of the docker registry to fetch the required docker images.")
    parser.add_argument("--version", action="version", version="%(prog)s v0.0.1")

    subparsers = parser.add_subparsers(help="sub-command help")

    local_test_patch_bundle = subparsers.add_parser("local-test-patch", help="Test the given patch locally")
    local_test_patch_bundle.add_argument("patch_id", help="The patch ID to test and run locally.")
    local_test_patch_bundle.add_argument("--mem-limit", default="512m", help="For docker run (default: 512m)")
    local_test_patch_bundle.add_argument("--mem-reservation", default="512m", help="For docker run (default: 512m)")

    local_test_patch_bundle.set_defaults(func=local_test_patch)

    local_download_patch_bundle = subparsers.add_parser("download-patch", help="Download the given patch id to a given directory (default of .), using the file scheme of service_<service_id>_team_<team_id>_patch_<patch_id>")
    local_download_patch_bundle.add_argument("patch_id", help="The patch ID to download locally")
    local_download_patch_bundle.add_argument("download_dir", default='.', nargs='?')
    local_download_patch_bundle.set_defaults(func=local_download_patch)

    update_patch_status_bundle = subparsers.add_parser("update-status", help="Update the status of the given patch_id with metadata.")
    update_patch_status_bundle.add_argument("patch_id", help="The patch ID to update the status.")
    update_patch_status_bundle.add_argument("status", choices=['accepted', 'sla_fail', 'sla_timeout', 'too_many_bytes'], help="The status.")
    update_patch_status_bundle.add_argument("metadata", nargs='?', help="The metadata is sent to the teams as feedback.")
    update_patch_status_bundle.set_defaults(func=update_patch_status)

    our_bin_diff_bundle = subparsers.add_parser("bin-diff", help="output our bin diff between two files.")
    our_bin_diff_bundle.add_argument("file_1", help="The first file")
    our_bin_diff_bundle.add_argument("file_2", help="The second file")
    our_bin_diff_bundle.set_defaults(func=our_bin_diff)

    warm_patchbot_bundle = subparsers.add_parser("warm-patchbot", help="Pull all the latest versions from all the services.")
    warm_patchbot_bundle.set_defaults(func=warm_patchbot)

    _args = parser.parse_args()

    if _args == argparse.Namespace():
        l.critical("Must specify a command")
        sys.exit(-1)
    else:
        _args.func(_args)
