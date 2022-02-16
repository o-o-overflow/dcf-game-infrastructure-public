#!/usr/bin/env python3
import argparse
import asyncio
import collections
import logging
import os
import pathlib
import shutil
import socket
import struct
import sys
import time

from ..database import Db

import dpkt

l = logging.getLogger("pcapbot")

# TODO: do this!
def anonymize_pcap(src, dst, keep_ip):
    # Start at 175.45.176.0
    fake_ip_address = 2939006975

    stealthed_packets = [ ]

    def new_fake_address():
        nonlocal fake_ip_address
        fake_ip_address += 1
        return socket.inet_ntoa(struct.pack('>I', fake_ip_address))

    ip_mapping = collections.defaultdict(new_fake_address)
    ip_mapping[keep_ip] = keep_ip
    try:
        pcap_reader = dpkt.pcap.Reader(open(src, 'rb'))
    except Exception:
        l.warning(f"file type is bad {sys.exc_info()[1]}, skipping.")
        return False, stealthed_packets
    pcap_writer = dpkt.pcap.Writer(open(dst, 'wb'))

    try:
        pcaps = list(pcap_reader)
    except dpkt.dpkt.NeedData:
        l.warning(f"pcap was too small {sys.exc_info()[1]}, skipping")
        return False, stealthed_packets

    for ts, buf in pcaps:
        try:
            eth = dpkt.ethernet.Ethernet(buf)
        except Exception:
            l.warning(f"error when attempting to decode packet, ignoring. {sys.exc_info()[1]}")
            continue
        if type(eth.data) != dpkt.ip.IP:
            l.warning(f"throwing away a packet that is not an IP packet {type(eth.data)}")
            continue
        ip = eth.data
        payload = ip.data
        if type(payload) != dpkt.tcp.TCP:
            l.warning(f"thowing away a non-TCP packet {type(payload)}")
            continue

        src_ip = socket.inet_ntoa(ip.src)
        dst_ip = socket.inet_ntoa(ip.dst)
        dst_port = ip.data.dport
        src_port = ip.data.sport

        if dst_ip == keep_ip and dst_port >= 10000 and dst_port <= 20000:
            stealthed_packets.append((src_ip, ts))
            continue
        elif src_ip == keep_ip and src_port >= 10000 and src_port <= 20000:
            stealthed_packets.append((dst_ip, ts))
            continue

        new_src_ip = ip_mapping[src_ip]
        new_dst_ip = ip_mapping[dst_ip]

        ip.src = socket.inet_aton(new_src_ip)
        ip.dst = socket.inet_aton(new_dst_ip)

        # set the ttl to 64 for all packets
        ip.ttl = 64

        orig_tcp_opts = dpkt.tcp.parse_opts(payload.opts)

        tcp_opts = bytearray(payload.opts)

        done = False
        index = 0
        # zero out the tcp timestamps
        while index < len(tcp_opts):
            o = tcp_opts[index]
            # 1 is TCP_OPT_NOP
            if o > 1:
                try:
                    # advance buffer at least 2 bytes = 1 type + 1 length
                    length = max(2, tcp_opts[index+1])
                    body = tcp_opts[index+2:index+length]
                    # 8 is TCP TIMESTAMP option
                    if o == 8:
                        size = len(tcp_opts[index+2:index+length])
                        tcp_opts[index+2:index+length] = size * b'\x00'
                    index += (2+length)
                except (IndexError, ValueError):
                    l.error("Bad options on the packet's opts")
                    break
            else:
                # options 0 and 1 are not followed by length byte
                index += 1

        payload.opts = bytes(tcp_opts)
        new_tcp_opts = dpkt.tcp.parse_opts(payload.opts)

        pcap_writer.writepkt(eth, ts)

    pcap_writer.close()
    return True, stealthed_packets

def check_structure(pcap_dir, services, teams):
    root = pathlib.Path(pcap_dir)
    if not root.exists():  # So that we can start running before dc2021f-infra/roles/game_pcap/tasks/main.yml
        os.mkdir(root, mode=0o755)
        shutil.chown(root, 'nobody', 'nogroup')
    for t in teams:
        team_dir = root.joinpath(str(t['id']))
        if not team_dir.exists():
            l.info(f"creating {team_dir}")
            team_dir.mkdir(0o755)
        for s in services:
            service_dir = team_dir.joinpath(str(s['id']))
            if not service_dir.exists():
                l.info(f"creating {service_dir}")
                service_dir.mkdir(0o755)
            necessary_dirs = ["new", "old", "processed", "released", "cur"]
            for d in necessary_dirs:
                usage_dir = service_dir.joinpath(d)
                if not usage_dir.exists():
                    l.info(f"creating {usage_dir}")
                    usage_dir.mkdir(0o755)


def main(the_db, pcap_dir="/pcap", poll_time_seconds=1, max_ticks=None, stealth_report_frequency=120):
    l.info("Started up the pcapbot.")
    i = 0
    while True:
        teams = the_db.teams()
        team_id_to_teams = {t['id']: t for t in teams}

        time.sleep(poll_time_seconds)
        pcap = pathlib.Path(pcap_dir)
        new_files_glob = '*/*/new/*'
        for to_process in pcap.glob(new_files_glob):
            l.info(f"file in {pcap_dir}/{new_files_glob} found {to_process}")
            team_id = to_process.parts[-4]
            service_id = to_process.parts[-3]
            if not int(team_id) in team_id_to_teams:
                l.info(f"Found pcap for non-existent team {team_id}, removing {to_process}\n")
                os.remove(to_process)
                i += 1
                if i == max_ticks:
                    l.info(f"Hit the max number of ticks {max_ticks} {i}")
                    return
                continue

            l.info(f"pcap for team {team_id} service {service_id}")

            processed_dir = to_process.parent.joinpath("../processed")
            released_dir = to_process.parent.joinpath("../released")

            if not processed_dir.exists():
                l.error(f"{processed_dir} does not exist")
                return

            if not released_dir.exists():
                l.error(f"{released_dir} does not exist")
                return

            filename = to_process.name
            base_filename = os.path.splitext(filename)[0]

            processed_filename = f"{base_filename}_anon.pcap"
            released_filename = f"{base_filename}_release.pcap"

            processed_path = processed_dir.joinpath(processed_filename)
            released_path = released_dir.joinpath(released_filename)

            l.info(f"processed path {processed_path} released path {released_path}")

            # New event that we received a pcacp should go to the DB

            reason = f"pcap found in {processed_path.parent} for team {team_id} service {service_id} filename {filename}"
            response = the_db.update_event(event_type="PCAP_CREATED",
                                           reason=reason,
                                           service_id=service_id,
                                           team_id=team_id,
                                           pcap_name=filename,
            )
            l.info(f"updated the DB with the pcap created event response code {response}")


            # Anonymize the new pcap and write it to processed
            archive_dir = to_process.parent.joinpath(f"../old/{to_process.name}")

            team_ip = f"10.13.37.{team_id}"
            file_created, stealthed_packets = anonymize_pcap(to_process, processed_path, team_ip)

            l.info(f"found {len(stealthed_packets)} stealthed packets")

            # report stealth attackers
            last_timestamps = { }
            for attacker_ip, timestamp in stealthed_packets:
                attacker_team = int(attacker_ip.split(".")[-2]) - 100
                # report one stealth event per five seconds per team
                if timestamp - last_timestamps.get(attacker_team, 0) > stealth_report_frequency:

                    last_timestamps[attacker_team] = timestamp
                    reason = f"detected packet on stealth port of service_id={service_id} attacker_ip={attacker_ip} src_team_id={attacker_team} dst_team_id={team_id} at {timestamp}"
                    l.info(reason)
                    response = the_db.new_timestamped_event(
                        event_type="STEALTH", reason=reason,
                        src_team_id=attacker_team, dst_team_id=team_id,
                        service_id=service_id, timestamp=timestamp
                    )
                    l.info(f"Updated the DB with the stealth event response {response}")

            # if successful, delete the original file
            if file_created:
                l.info("Anonmyization was a success.")
                l.info(f"Saving to {archive_dir}")
                to_process.rename(archive_dir)
            else:
                l.error(f"anonmyization fail, going to give up processing {to_process}.")
                to_process.rename(archive_dir)
                i += 1
                if i == max_ticks:
                    l.info(f"Hit the max number of ticks {max_ticks} {i}")
                    return
                continue

            # if we are releasing PCAPs, copy the anonmyized pcap from processed to released
            service = the_db.service(service_id)

            if service['release_pcaps']:
                reason = f"releasing pcap {released_filename} for team {team_id} service {service_id}"
                l.info(reason)
                shutil.copyfile(processed_path, released_path)
                response = the_db.update_event(event_type="PCAP_RELEASED",
                                               reason=reason,
                                               service_id=service_id,
                                               team_id=team_id,
                                               pcap_name=released_filename,
                )
                l.info(f"Updated the DB with the pcap released event response {response}")

            i += 1
            if i == max_ticks:
                l.info(f"Hit the max number of ticks {max_ticks} {i}")
                return

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="pcapbot")
    parser.add_argument("--dbapi", help="The location of the database API")
    parser.add_argument("--pcap-dir", default="/pcap", help="The location of the pcap structure")
    parser.add_argument("--verify-dirs", action='store_true', help="Verify the pcap structure")
    parser.add_argument("--version", action="version", version="%(prog)s v0.0.2")

    args = parser.parse_args()

    database_api = None
    if args.dbapi:
        database_api = args.dbapi
    elif 'DATABASE_API' in os.environ:
        database_api = os.environ['DATABASE_API']

    pcap_dir = args.pcap_dir

    the_db = Db(database_api)
    if args.verify_dirs:
        check_structure(pcap_dir, the_db.services(), the_db.teams())

    main(the_db, pcap_dir=pcap_dir)
