#!/usr/bin/env python3
"""
gamestate tests
"""
import io
import os
import socket
import time
import unittest.mock

import docker

import ooogame.patchbot.patchbot as patchbot
from ooogame.database.api import PatchStatus
from ooogame.database.client import Db

def test_bin_diff():
    a = b"adamtest"
    diff = patchbot.bin_diff(a, a)
    assert diff == 0

    diff = patchbot.bin_diff(a, b"")
    assert diff == len(a)

    a = b"adamtest"
    b = b"acamtest"
    diff = patchbot.bin_diff(a, b)
    assert diff == 1

    a = b"adamtest"
    b = b"acamtasa"
    diff = patchbot.bin_diff(a, b)
    assert diff == 3

def test_test_patch():
    db = Db("", True)
    start_game = db.start_game()

    service = [s for s in db.services() if s['type'] == 'NORMAL'][0]
    service_id = service['id']

    # activate service 1
    response = db.test_client.post(f"/api/v1/service/{service_id}/is_active/1")

    i = 0
    for status in [PatchStatus.ACCEPTED, PatchStatus.TOO_MANY_BYTES, PatchStatus.SLA_TIMEOUT, PatchStatus.SLA_FAIL]:
        i += 1
        result = db.upload_patch(i+1, service_id, b"this is a test")
        assert result

        with unittest.mock.patch("ooogame.patchbot.patchbot.check_and_deploy_service", unittest.mock.Mock(return_value=(status, "metadata"))):
            result = patchbot.test_patch(i, the_db=db, registry="testing/")
            assert result

            result = patchbot.test_patch(i, the_db=db, registry="testing/", update_db=False, deploy_service=False)
            assert result

            patch = db.patch(i)
            assert patch['results'][0]['status'] == status.name

def test_warm_patchbot():
    test_services = [{'id': 1, 'name': 'test-1', 'type': 'KING_OF_THE_HILL'},
                     {'id': 2, 'name': 'testing', 'type': 'NORMAL', 'service_docker': 'ubuntu:18.04', 'interaction_docker': 'httpd:alpine', 'local_interaction_docker': 'xko8984i4192804u219hjifldsjklfdjs'}]

    with unittest.mock.patch("ooogame.database.client.Db.services", unittest.mock.Mock(return_value=test_services)):
        db = Db("", True)
        start_game = db.start_game()

        args = unittest.mock.Mock()
        args.registry = ''

        patchbot.warm_patchbot(args, the_db=db)


def test_get_public_metadata():
    result = patchbot.get_public_metadata(b"foobar")
    assert result == None

    result = patchbot.get_public_metadata(b"I am some output\nPUBLIC: foobar\nother")
    assert result == b"foobar"

    result = patchbot.get_public_metadata(b"I am some output\nPUBLIC: THIS BAD\nother\nPUBLIC: another")
    assert result == b"THIS BAD\nanother"

ETC_SHELLS = b"""# /etc/shells: valid login shells
/bin/sh
/bin/bash
/bin/rbash
/bin/dash
"""    
def test_core_patchbot_functionality():
    client = docker.from_env()
    api = docker.APIClient()
    try:
        local_testing_tag = None
        testing_tag_sleepy = None
        testing_tag_my_fail = None
        container = client.containers.run("ubuntu:18.04", command="sleep 2d", detach=True, auto_remove=True)

        # Test getting IP
        ip = patchbot.get_ip(api, container.name)
        assert ip

        # Test getting a consistent network name
        network_name = patchbot.get_docker_network(client, 1)
        assert network_name

        same_network_name = patchbot.get_docker_network(client, 1)
        assert network_name == same_network_name

        other_network_name = patchbot.get_docker_network(client, 2)
        assert other_network_name != network_name

        # Test getting files from container
        archive = patchbot.get_file_from_container_as_tar(container, "/etc/shells")

        assert len(archive.getmembers()) == 1
        file_info = archive.getmember("shells")
        content = archive.extractfile("shells").read()
        assert content == ETC_SHELLS
        assert file_info.uid == 0
        assert file_info.gid == 0
        assert (file_info.mode & 0xFFF) == 0o644

        # Test putting files into the container
        new_file_content = b"hello_world"

        result = patchbot.drop_file_on_container(container, "/hello", new_file_content, 0o467, 0, 10)
        assert result

        archive = patchbot.get_file_from_container_as_tar(container, "/hello")
        file_info = archive.getmember("hello")
        assert file_info.uid == 0
        assert file_info.gid == 10
        assert (file_info.mode & 0xFFF) == 0o467

        content = archive.extractfile("hello").read()
        assert content == new_file_content

        # Can we overwrite the file that's already there? 
        new_file_content = b"new_content"

        result = patchbot.drop_file_on_container(container, "/hello", new_file_content, 0o777, 10, 0)
        assert result

        archive = patchbot.get_file_from_container_as_tar(container, "/hello")
        file_info = archive.getmember("hello")
        assert file_info.uid == 10
        assert file_info.gid == 0
        assert (file_info.mode & 0xFFF) == 0o777

        content = archive.extractfile("hello").read()
        assert content == new_file_content

        # Test get patch byte diff

        diff, info = patchbot.get_patch_byte_diff(container, "/hello", b"new_content")
        assert diff == 0
        assert info.uid == file_info.uid
        assert info.gid == file_info.gid
        assert info.mode == file_info.mode
        diff, _ = patchbot.get_patch_byte_diff(container, "/hello", b"new content")
        assert diff == 1
        diff, _ = patchbot.get_patch_byte_diff(container, "/hello", b"aaa content")
        assert diff == 4

        # test get_patch_tag

        result = patchbot.get_patch_tag(1, 2)
        assert result
        same_result = patchbot.get_patch_tag(1, 2)
        assert result == same_result

        # test patch_file_and_tag but we want to
        testing_tag = "testing-patchbot"
        remove_image_if_exists(client, testing_tag)

        patched_content = b"i am the new file"
        result = patchbot.patch_file_and_tag(container, testing_tag, "/hello", patched_content, 0o777, 0, 0)
        assert result
        assert client.images.get(testing_tag)

        # did the file actually change?
        try:
            new_patch_container = client.containers.run(testing_tag, detach=True, auto_remove=True)
            assert new_patch_container
            archive = patchbot.get_file_from_container_as_tar(new_patch_container, "/hello")
            file_info = archive.getmember("hello")
            assert file_info.uid == 0
            assert file_info.gid == 0
            assert (file_info.mode & 0xFFF) == 0o777

            content = archive.extractfile("hello").read()
            assert content == patched_content
        finally:
            new_patch_container.kill()


        # Create a docker imgae that will loop forever, to use in timeout testing
        testing_tag_sleepy = "testing-patchbot-sleepy"
        remove_image_if_exists(client, testing_tag_sleepy)
        patched_content = b"""#!/bin/sh -e
echo "PUBLIC: sleepy"
sleep 100d
"""
        result = patchbot.patch_file_and_tag(container, testing_tag_sleepy, "/sleep", patched_content, 0o777, 0, 0)

        testing_tag_my_fail = "testing-patchbot-my-fail"
        remove_image_if_exists(client, testing_tag_my_fail)
        patched_content = b"""#!/bin/sh -e
echo "PUBLIC: public output"
exit -1
"""
        result = patchbot.patch_file_and_tag(container, testing_tag_my_fail, "/my-fail", patched_content, 0o777, 0, 0)

        team_id = 1

        # Test remote interactions (with all fake stuff)
        result, metadata = patchbot.test_remote_interactions(client, api, testing_tag, "ubuntu:18.04", network_name, ["/bin/true"], 8080, 60, team_id)
        assert result == True

        result, metadata = patchbot.test_remote_interactions(client, api, testing_tag, testing_tag_my_fail, network_name, ["/my-fail"], 8080, 60, team_id)
        assert result == PatchStatus.SLA_FAIL
        assert metadata == b"public output"

        result, metadata = patchbot.test_remote_interactions(client, api, testing_tag, testing_tag_sleepy, network_name, ["/sleep"], 8080, 0.5, team_id)
        assert result == PatchStatus.SLA_TIMEOUT
        assert metadata == b"sleepy"

        local_testing_tag = f"{testing_tag}-local"

        # test local interactions (with all fake stuff)
        result, metadata = patchbot.test_local_changes(client, api, local_testing_tag, "httpd:alpine", "/test", b"content", 0o777, 0, 0, network_name, [], 60, team_id)
        assert result == True

        result, metadata = patchbot.test_local_changes(client, api, local_testing_tag, "httpd:alpine", "/test", b"content", 0o777, 0, 0, network_name, ["/bin/true"], 60, team_id)
        assert result == True

        result, metadata = patchbot.test_local_changes(client, api, local_testing_tag, testing_tag_my_fail, "/test", b"content", 0o777, 0, 0, network_name, ["/my-fail"], 60, team_id)
        assert result == PatchStatus.SLA_FAIL
        assert metadata == b"public output"

        result, metadata = patchbot.test_local_changes(client, api, local_testing_tag, testing_tag_sleepy, "/test", b"content", 0o777, 0, 0, network_name, ["/sleep"], 0.5, team_id)
        assert result == PatchStatus.SLA_TIMEOUT
        assert metadata == b"sleepy"

        result, metadata = patchbot.test_local_changes(client, api, local_testing_tag, "httpd:alpine", "/bin/true", b"wrong_content", 0o777, 0, 0, network_name, ["/bin/true"], 60, team_id)
        assert result == PatchStatus.SLA_FAIL

        # Test deploying a container
        registry_container = None
        try:
            registry_container = client.containers.run("registry", ports={'5000/tcp': None}, detach=True, auto_remove=True)
            while not registry_container.ports:
                time.sleep(.5)
                registry_container.reload()

            registry_port = list(registry_container.ports.values())[0][0]['HostPort']
            while registry_container.status != 'running':
                time.sleep(.5)                
                registry_container.reload()

            local_registry_tag = f"localhost:{registry_port}/{testing_tag}"
            result = patchbot.deploy_container(client, api, testing_tag, local_registry_tag)
            assert result

            result = client.images.pull(local_registry_tag)
            assert result

            # Test the whole shebang
            remove_image_if_exists(client, testing_tag)
            patchbot.get_patch_tag = unittest.mock.Mock(return_value=testing_tag)

            local_registry_tag = f"localhost:{registry_port}/{testing_tag}-2"

            result, metadata = patchbot.check_and_deploy_service(client, api, "httpd:alpine", local_registry_tag, remote_interaction_container_name="ubuntu:18.04", local_interaction_container_name="httpd:alpine", patch_id=10, service_id=1, service_port=8080, remote_interaction_scripts=["/bin/true"], local_interaction_scripts=["/bin/true"], docker_location_to_patch="/etc/shells", new_file=ETC_SHELLS, max_bytes=10000, check_timeout=60, pull_latest=False, team_id=team_id)
            assert result == PatchStatus.ACCEPTED

            result, metadata = patchbot.check_and_deploy_service(client, api, "httpd:alpine", local_registry_tag, remote_interaction_container_name="ubuntu:18.04", local_interaction_container_name="httpd:alpine", patch_id=10, service_id=1, service_port=8080, remote_interaction_scripts=["/bin/true"], local_interaction_scripts=["/bin/true"], docker_location_to_patch="/etc/shells", new_file=ETC_SHELLS, max_bytes=10000, check_timeout=60, pull_latest=False, deploy_service=False, team_id=team_id)
            assert result == PatchStatus.ACCEPTED
            

            result, metadata = patchbot.check_and_deploy_service(client, api, "httpd:alpine", local_registry_tag, remote_interaction_container_name=testing_tag_my_fail, local_interaction_container_name="httpd:alpine", patch_id=10, service_id=1, service_port=8080, remote_interaction_scripts=["/my-fail"], local_interaction_scripts=["/bin/true"], docker_location_to_patch="/etc/shells", new_file=ETC_SHELLS, max_bytes=10000, check_timeout=60, pull_latest=False, team_id=team_id)
            assert result == PatchStatus.SLA_FAIL
            assert metadata == b"public output"

            result, metadata = patchbot.check_and_deploy_service(client, api, "httpd:alpine", local_registry_tag, remote_interaction_container_name="ubuntu:18.04", local_interaction_container_name="httpd:alpine", patch_id=10, service_id=1, service_port=8080, remote_interaction_scripts=["/bin/true"], local_interaction_scripts=["/bin/false"], docker_location_to_patch="/etc/shells", new_file=ETC_SHELLS, max_bytes=10000, check_timeout=60, pull_latest=False, team_id=team_id)
            assert result == PatchStatus.SLA_FAIL
            
            result, metadata = patchbot.check_and_deploy_service(client, api, "httpd:alpine", local_registry_tag, remote_interaction_container_name=testing_tag_sleepy, local_interaction_container_name=testing_tag_sleepy, patch_id=10, service_id=1, service_port=8080, remote_interaction_scripts=["/sleep"], local_interaction_scripts=["/bin/true"], docker_location_to_patch="/etc/shells", new_file=ETC_SHELLS, max_bytes=10000, check_timeout=0.5, pull_latest=False, team_id=team_id)
            assert result == PatchStatus.SLA_TIMEOUT
            assert metadata == b"sleepy"

            result, metadata = patchbot.check_and_deploy_service(client, api, "httpd:alpine", local_registry_tag, remote_interaction_container_name=testing_tag_sleepy, local_interaction_container_name=testing_tag_sleepy, patch_id=10, service_id=1, service_port=8080, remote_interaction_scripts=["/bin/true"], local_interaction_scripts=["/sleep"], docker_location_to_patch="/etc/shells", new_file=ETC_SHELLS, max_bytes=10000, check_timeout=0.5, pull_latest=False, team_id=team_id)
            assert result == PatchStatus.SLA_TIMEOUT
            assert metadata == b"sleepy"

            result, metadata = patchbot.check_and_deploy_service(client, api, "httpd:alpine", local_registry_tag, remote_interaction_container_name="ubuntu:18.04", local_interaction_container_name="httpd:alpine", patch_id=10, service_id=1, service_port=8080, remote_interaction_scripts=["/bin/true"], local_interaction_scripts=[], docker_location_to_patch="/etc/shells", new_file=b"wrong content", max_bytes=1, check_timeout=60, pull_latest=False, team_id=team_id)
            assert result == PatchStatus.TOO_MANY_BYTES

        finally:
            if registry_container:
                registry_container.kill()
            
    finally:
        container.kill()
        if testing_tag:
            remove_image_if_exists(client, testing_tag)
        if local_testing_tag:
            remove_image_if_exists(client, local_testing_tag)
        if testing_tag_sleepy:
            remove_image_if_exists(client, testing_tag_sleepy)
        if testing_tag_my_fail:
            remove_image_if_exists(client, testing_tag_my_fail)

def remove_image_if_exists(client, name):
    try:
        img = client.images.remove(name)
    except docker.errors.ImageNotFound:
        pass
