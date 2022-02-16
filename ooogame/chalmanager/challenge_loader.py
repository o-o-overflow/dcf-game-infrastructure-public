#!/usr/bin/env python3
from os.path import abspath, basename, isfile, isdir, join
import hmac
import json
import logging
import os
import re
import subprocess
import sys
import tarfile
from typing import Dict,List,Optional

import boto3
import click
import coloredlogs
import yaml


assert sys.version_info[0] == 3

GIT_PATH_T = "git@github.com:o-o-overflow/dc2021f-%s.git"

PUBLIC_FILENAME_RE = r"[/a-zA-Z0-9_.@-]+\Z"  # mostly for sanity  NOW INCLUDES / (full filepath)



LOGGER = logging.getLogger(__name__)
coloredlogs.install(level=os.getenv("LOGLEVEL","INFO"), logger=LOGGER)

MANDATORY_FIELDS = [
    "service_name", "description", "type", "tags", "authors",
]
MANDATORY_NORMAL_FIELDS = [ "patchable_file", "flag_path", "max_patchable_bytes"]
MANDATORY_KOH_FIELDS = ["score_path"]
S3_BUCKET = "dc2021f-challs-b"
S3_PROFILE = "ooo"

VALID_CATEGORIES = {"normal", "king_of_the_hill"}

HASH_SALT = b"OMGWHATokweredoingthisthingagaindunnyientuchpenWynvow5kni"


def ask(prompt):
    if ('CI' in os.environ) or not (sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty()):
        LOGGER.warning("Non-interactive, skipping question '%s'", prompt)
        return None
    r = input(prompt)
    if r.lower() in ('n','no'):
        return False
    return r


def get_s3():
    avail = boto3.Session().available_profiles
    session = boto3.Session(profile_name=S3_PROFILE if (S3_PROFILE in avail) else None)
    return session.resource("s3")


class Challenge():
    def __init__(self, info, repo_dir):
        self.id = info["id"]
        self.title = info["service_name"]
        self.description = info["description"]
        if '\n' in re.sub(r'\n{2,}', '', self.description.strip()):
            LOGGER.warning("Lonely newline detected in %s's description -- Markdown will ignore it.", self.id)

        if info.get("public_files"):
            self.public_files: List[str] = list(map(lambda fp: abspath(join(repo_dir, fp)),
                                    info["public_files"]))
        else:
            self.public_files: List[str] = []
        self.type = info["type"].lower()
        self.tags: List[str] = info["tags"]
        self.authors = info["authors"]

        self.violates_flag_format = info.get("violates_flag_format", False)

        self.exploit_scripts = []
        self.sla_scripts = []
        self.test_scripts = []
        if "remote_interactions" in info and info["remote_interactions"]:
            for fn in info["remote_interactions"]:
                if basename(fn).startswith("exploit"):
                    self.exploit_scripts.append(fn)
                elif basename(fn).startswith("check"):
                    self.sla_scripts.append(fn)

        self.repo_url = GIT_PATH_T % self.title

        self.limit_memory = info.get("limit_memory", "512m")
        self.request_memory = info.get("request_memory", "512m")
        assert re.match(r'[0-9]+[bkmg]', self.limit_memory, re.IGNORECASE)
        assert re.match(r'[0-9]+[bkmg]', self.request_memory, re.IGNORECASE)

        self.commit = info["commit"] if "commit" in info else "latest"

        self.patchable_file_from_docker = info["patchable_file"] if "patchable_file" in info else ""
        if isinstance(self.patchable_file_from_docker, list):  # TODO: but it's a list again below?
            assert len(self.patchable_file_from_docker) == 1
            self.patchable_file_from_docker = self.patchable_file_from_docker[0]

        self.max_patchable_bytes = info["max_patchable_bytes"] if self.type == "normal" else "0"
        self.is_manual_patching = info["is_manual_patching"] if "is_manual_patching" in info else False

        self.container_port = info["container_port"] if "container_port" in info else self.get_expose_from_docker(repo_dir)
        self.port = info.get("game_port", self.container_port)
        if self.port != self.container_port:
            print("WARNING: game_port %d != container_port %d" % (self.port, self.container_port))

        self.flag_location = info["flag_path"] if self.type == "normal" else ""
        self.central_server = info["central_server"] if "central_server" in info else ""
        self.isolation = info["isolation"].upper() if self.type == "normal" else None
        if self.type == "normal":
            assert(self.isolation == "PRIVATE" or self.isolation == "SHARED")

        self.score_location = info["score_location"] if self.type == "king_of_the_hill" else ""
        if isinstance(self.score_location, list):
            self.score_location = self.score_location[0]

        self.local_interaction_scripts = info['local_tests'] if 'local_tests' in info else []

        self.execution_profile = info["execution_profile"] if "execution_profile" in info else ""
        self.description = f"""<div class="d-inline-block col-md-12 service-details">{self.description}</div>"""
        self.check_timeout = info["check_timeout"] if "check_timeout" in info else 120 #default

        if self.public_files:
            s3key = "{}.tar.gz".format(hmac.new(key=HASH_SALT, msg=self.title.encode("utf-8"), digestmod='sha256').hexdigest())
            #self.description += "<br/> <a href="https://s3.us-east-2.amazonaws.com/{}/{}">Download Files</a>".format(S3_BUCKET, s3key)
            #https://ooo-finals-challs.s3.amazonaws.com/
            url = "https://dc2021f-challs-b.s3.amazonaws.com/{}".format(s3key)
            self.description += f"""<div class="d-inline-block col-md-7 service-details "><a href="{url}">Download Challenge</a></div>"""

        if len(self.patchable_file_from_docker) > 0:
            pfs = self.patchable_file_from_docker
            if isinstance(pfs, str):
                pfs = [pfs]
            for pf in pfs:
                self.description += f"""<div class="d-inline-block col-md-7 service-details">File to patch: {os.path.basename(pf)}</div>"""
        if self.flag_location and not self.central_server:
            self.description += f"""<div class="d-inline-block col-md-7 service-details">Flag Location: {self.flag_location}</div>"""
        if self.type == "normal":
            self.description += f"""<div class="d-inline-block col-md-7 service-details">Max Patchable Bytes: {self.max_patchable_bytes}</div>"""
        if self.violates_flag_format:
            self.description += """<div class="d-inline-block col-md-7 service-details">Note: this service has a non-standard flag format.</div>"""


    def __str__(self):
        # TODO
        return "<Chall {}>".format(self.id)

    def get_expose_from_docker(self, repo_dir):
        ddata = open(join(repo_dir, "service", "Dockerfile"),"r").read()
        ptrn = re.compile(r"EXPOSE[ \s]{1,10}(?P<port>[0-9]{1,6})", flags=re.IGNORECASE)

        search = re.search(ptrn, ddata)

        if search:
            assert len(list(re.finditer(ptrn, ddata))) == 1
            return int(search.group("port"))
        else:
            print("Error, port not in Dockerfile")
            exit(-1)

    def process_public_files(self):
        s3 = get_s3()
        service_dir = "./cloned_repos/chall-{}".format(self.title)

        # XXX: Changed to do directories, since we're distributing the tgz
        tar_fp = os.path.join(service_dir, "public_bundle.tar.gz")
        if os.path.exists(tar_fp):
            os.unlink(tar_fp)
        with tarfile.open(tar_fp, "w:gz") as tar:
            done = []
            for f in self.public_files:
                arcname = os.path.join(self.title, f)
                ic = arcname.index('cloned_repos')
                arcname = arcname[ic+len('cloned_repos/chall-'):]
                print(f"adding {f} to the public files -> {arcname} in tar ...")
                # NOTE: This logic should match ./tester
                assert os.path.exists(f), "Public file not found: {} -- remember that all public files must be pre-built and checked into git".format(f)
                assert os.path.isfile(f), "Only regular files for the public: {}".format(f)
                assert not os.path.islink(f), "No symlinks for the public: {}".format(f)
                assert f not in done, f"We already processed a '{f}' file!"

                assert re.match(PUBLIC_FILENAME_RE, f), "Weird name for a public file: {} -- can it match '{}' instead?".format(f, PUBLIC_FILENAME_RE)

                def anonymize(t):
                    t.mtime = t.uid = t.gid = 0; t.uname = t.gname = ""; t.pax_headers.clear()
                    return t
                tar.add(f, arcname=arcname, filter=anonymize)
                done.append(f)

        subprocess.check_output(["tar", "tvzf", tar_fp])
        print(f"Created {tar_fp}")

        s3key = "{}.tar.gz".format(hmac.new(key=HASH_SALT, msg=self.title.encode("utf-8"), digestmod='sha256').hexdigest())
        with open(tar_fp, "rb") as fp:
            LOGGER.info(f"Uploading to S3: {s3key}")
            s3.meta.client.upload_fileobj(fp, S3_BUCKET, s3key)

            # Make it so the s3 object we just uploaded is publically accessible

            obj = s3.Object(S3_BUCKET, s3key)
            obj.Acl().put(ACL="public-read")
            LOGGER.info('Changed ACL on S3 key {} to \"public-read\''.format(s3key))

        del self.public_files

    def get_yaml(self):

        out_dict = {"id": self.id,
                    "name": self.title,
                    "type": self.type.upper(),
                    "description": self.description,
                    "patchable_file_from_docker": self.patchable_file_from_docker,
                    "max_bytes": self.max_patchable_bytes,
                    "check_timeout": self.check_timeout,
                    "port": self.port,
                    "container_port": self.container_port,
                    "repo_url": self.repo_url,
                    "commit": self.commit,
                    "execution_profile": self.execution_profile,
                    "exploit_scripts": self.exploit_scripts,
                    "sla_scripts": self.sla_scripts,
                    "local_interaction_scripts": self.local_interaction_scripts,
                    "flag_location": self.flag_location,
                    "central_server": self.central_server,
                    "isolation": self.isolation,
                    "score_location": self.score_location,
                    "is_manual_patching": self.is_manual_patching,
                    "limit_memory": self.limit_memory,
                    "request_memory": self.request_memory,
        }
        return out_dict


@click.group()
def cli():
    pass


@cli.command()
@click.argument("chall_name", type=str)
@click.argument("challs_fp", default="defcon-finals-2021.challs", type=str)
def upload(chall_name, challs_fp):
    LOGGER.warning("assuming challange %s is already pulled and up-to-date", chall_name)

    chall_dir = f"./cloned_repos/chall-{chall_name}"

    if not isdir(chall_dir):
        print (f"Error, {chall_name} is not a valid chall id")
        return -1

    chall_id = get_challenge_id(chall_name, challs_fp)

    challenge = load_chall(chall_dir, chall_id)

    if not challenge:
        print (f"Error, {chall_id} seems malformed")
        return -1

    challenge.process_public_files()


    print (f"chall_id: {chall_id}" )

def output_service_info_yaml(yaml_out_fp, challs):
    # TODO: is this the main output function?

    data = dict()

    services = []

    ports_seen = {}

    for name, chall in challs.items():
        y = chall.get_yaml()
        if y.get('port'):
            if y['port'] in ports_seen:
                LOGGER.critical("Service %s has the same game_port %d as %s",
                        y['name'], y['port'], ports_seen[y['port']])
            ports_seen[y['port']] = y['name']
        services.append(y)

    data["services"] = services

    # removed this default services, but keeping it in for now in case
    # we want to use it for the future, it is quite handy

    # with open("default_values_service_info.yml", "r") as yaml_inp_file:
    #     default_srv_data = yaml.safe_load(yaml_inp_file)["services"]

    # for index in range(0, len(default_srv_data)):
    #     if index >= len(data["services"]):
    #         data["services"].append(default_srv_data[index])

    with open(yaml_out_fp,"w") as yaml_file:
        yaml.dump(data, yaml_file)

@cli.command()
@click.option("--challs", "challs_fp", default="defcon-finals-2021.challs")
@click.option("--yaml","yaml_out_fp", default="service_info.yml")
@click.option("-o", "--output_dir", "output_dir", default="cloned_repos")
@click.option("-y", "--yes", "--assume-yes", "assume_yes", is_flag=True,
              default=False)
def loadall(challs_fp, yaml_out_fp, output_dir, assume_yes):
    challs = load_all_challs(challs_fp, output_dir, assume_yes=assume_yes)
    output_service_info_yaml(yaml_out_fp, challs)

    print("------------ SUMMARY -------------")
    print(f"Attempted to load {len(challs)} challs")
    for name, chall in challs.items():
        print(f"{name} ~> {'OK' if chall is not None else 'ERROR'}")


def load_all_challs(challs_fp, output_dir, assume_yes=True, update=True) -> Dict[str,Optional[Challenge]]:
    challenges = parse_challs_file_with_ids(challs_fp)
    output_dir = abspath(output_dir)
    if update:
        if not assume_yes:
            input(f"About to clone {len(challenges)} repos to {output_dir}, OK? [press enter]")

        for name in challenges.values():
            clone_chall_repo(name, output_dir)

    challs = {}
    for chall_id, name in challenges.items():
        assert name.strip()
        LOGGER.info(f"Loading {name} chall")

        chall_dir = join(output_dir, f"chall-{name}")
        chall = load_chall(chall_dir, chall_id)

        if chall is None:
            LOGGER.error(f"At least one error with chall {name}")
        else:
            LOGGER.info("All good!")

        challs[name] = chall

    return challs


# Load one challenge
@cli.command()
@click.argument("name", type=str)
@click.option("--challs", "challs_fp", default="defcon-finals-2021.challs")
@click.option("-o", "--output_dir", "output_dir", default="cloned_repos")
@click.option("-y", "--yes", "--assume-yes", "assume_yes",
        is_flag=True, default=False)
def loadone(name, challs_fp, output_dir, assume_yes):
    LOGGER.info(f"Challenge {name} is found.")
    # update the repo
    if not assume_yes:
        ch = input(f"About to clone {name} to {output_dir}, OK? [Y/N] ")
        if len(ch) != 1 or ch[0] != 'Y':
            print("Cya")
            sys.exit()
    clone_chall_repo(name, output_dir)

    chall_id = get_challenge_id(name, challs_fp)
    if chall_id is None:
        LOGGER.error(f"Challenge {name} is not found")
        return

    # load the challenge info from info.yml
    chall_dir = join(output_dir, f"chall-{name}")
    chall = load_chall(chall_dir, chall_id)
    if chall is None:
        LOGGER.error(f"At least one error with chall {name}")
    else:
        LOGGER.info("All good!")


def get_challenge_id(challenge, challs_fp):
    LOGGER.info(f"Finding {challenge} from {challs_fp} for challenge id")
    challenges = parse_challs_file_with_ids(challs_fp)
    for c_id, c_name in challenges.items():
        if c_name == challenge:
            return c_id
    return None


@cli.command()
@click.argument("output_file", default="scoreboard.json")
@click.option("--challs", "challs_fp", default="defcon-finals-2021.challs")
@click.option("-o", "--output_dir", "output_dir", default="cloned_repos")
def scoreboard(output_file, challs_fp, output_dir):
    LOGGER.warning("This action will delete all current AWS public files, re-upload, re-do the scoreboard from zero.")
    if not ask("Have you already done loadall + pulled new changes?"):
        return 3
    if os.path.isfile(output_file):
        if subprocess.call(['cp','-p','--backup=numbered', output_file, output_file+".bak"]) != 0:
            subprocess.check_call(['cp','-pf', output_file, output_file+".bak"])
    LOGGER.warning("Remaking %s anew", output_file)

    challenges = load_all_challs(challs_fp, output_dir, update=False)
    delete_everything_in_our_bucket()

    challenges_data = []
    skipped = []
    for challenge_name in sorted(challenges.keys()):
        challenge = challenges[challenge_name]
        if challenge is None:
            skipped.append(challenge_name)
            continue
        LOGGER.info("--- full scoreboard ---> %s", challenge_name)

        challenge.process_public_files()   # Maybe TODO: implement in terms of single update_chall() command

        challenges_data.append(vars(challenge))

    with open(output_file, "w") as fp:
        json.dump(challenges_data, fp, indent=2, sort_keys=True)

    print("------------ SUMMARY FOR %s -------------" % output_file)
    for n in challenges:
        print(n)
    if skipped:
        print("SKIPPED: {}", skipped)



@cli.command()
@click.argument("chall_id", type=str)
def test_chall(chall_id):
    chall_dir = "./cloned_repos/chall-{}".format(chall_id)
    LOGGER.info("Loading chall at %s" % chall_dir)
    chall_dir = abspath(chall_dir)
    if ask("Do you want to git pull first?"):
        subprocess.check_call(['git','-C',chall_dir,'pull','--ff-only'])
    chall = load_chall(chall_dir, chall_id=1)
    if chall is None:
        LOGGER.error(f"At least one error with chall at {chall_dir}")
    else:
        LOGGER.info("All good!")
    # TODO: some form of test_deployed?


def delete_everything_in_our_bucket():
    s3 = get_s3()
    bucket = s3.Bucket(S3_BUCKET)
    for o in bucket.objects.all():
        LOGGER.info(f"Deleting object {str(o)} in bucket {S3_BUCKET}")
        o.delete()


def parse_challs_file_with_ids(challs_fp) -> Dict[int,str]:
    challenges = {}
    with open(challs_fp) as f:
        lines = f.read().split("\n")
        for i, line in enumerate(lines):
            line = line.strip()
            if line == '' or line.startswith('#'):
                continue
            chall_name, chall_id = line.split(',')
            challenges[int(chall_id)] = chall_name
    return challenges


def clone_chall_repo(name, output_dir):
    git_repo_path = GIT_PATH_T % name
    repo_dir = join(output_dir, "chall-%s" % name)
    LOGGER.info(f"getting {name}")
    if not isdir(repo_dir):
        # git clone
        cmd = ['git', 'clone', '-q', git_repo_path, repo_dir]
    else:
        # git pull
        cmd = ['git', '-C', repo_dir, 'pull', '--ff-only', '-q']
    LOGGER.info("Exec %s", ' '.join(cmd))
    subprocess.check_call(cmd)


def load_chall(chall_dir, chall_id) -> Optional[Challenge]:
    yaml_fp = join(chall_dir, "info.yml")

    if not isfile(yaml_fp):
        LOGGER.error(f"missing YAML file (expected: {yaml_fp})")
        return None

    with open(yaml_fp, "rb") as f:
        info = yaml.safe_load(f)

    # check for fields
    ok = True
    for field in MANDATORY_FIELDS:
        if field not in info.keys():
            LOGGER.error(f"missing field {field}")
            ok = False
    if info["type"].lower() == "normal":
        if "patchable_files" in info and "patchable_file" not in info:
            info["patchable_file"] = info["patchable_files"]

        for field in MANDATORY_NORMAL_FIELDS:
            if field not in info.keys():
                LOGGER.error(f"missing the mandatory NORMAL field {field}")
                ok = False

    if not ok:
        LOGGER.error("At least one error with the yaml")
        return None

    ok = True
    if info.get("public_files"):
        for fp in info["public_files"]:
            fp = abspath(join(chall_dir, fp))
            if not isfile(fp):
                LOGGER.error(f"public file '{fp}' not found")
                ok = False
    if not ok:
        LOGGER.critical("ERROR on public files")
        # continuing as requested (Adam?) return None

    if info["service_name"].find(' ') >= 0:
        LOGGER.error("chall name must be one single word")
        return None

    info["id"] = chall_id

    chall = Challenge(info, chall_dir)
    return chall


# def hash_flag(flag):
#     if len(flag) > 160:
#         LOGGER.error("flag {} is more than 160 bytes".format(flag))
#     return hashlib.sha256(flag.encode()).hexdigest()


if __name__ == "__main__":
    cli()
