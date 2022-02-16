#!/usr/bin/env python3
"""
gamebot tests
"""

import socket
import dpkt
import time
import os
import io

from pyfakefs.fake_filesystem_unittest import Patcher

import ooogame.pcapbot.pcapbot as pcapbot
from ooogame.database.client import Db

def check_anonymization(pcap_data, invalid_ips, valid_ips):
    """
    Check that the pcap at location pcap_location does not have any
    packts from the list of invalid_ips, and has packets from the list
    of valid_ips.
    """
    pcap_reader = dpkt.pcap.Reader(io.BytesIO(pcap_data))
    seen_ips = set()
    seen_ttls = set()
    for ts, buf in pcap_reader:
        eth = dpkt.ethernet.Ethernet(buf)
        ip = eth.data
        src_ip = socket.inet_ntoa(ip.src)
        dst_ip = socket.inet_ntoa(ip.dst)
        seen_ips.add(src_ip)
        seen_ips.add(dst_ip)
        seen_ttls.add(ip.ttl)

        assert not src_ip in invalid_ips
        assert not dst_ip in invalid_ips

    for valid in valid_ips:
        assert valid in seen_ips

    assert len(seen_ttls) == 1, seen_ttls
        

def test_pcapbot():
    db = Db("", True)

    start_game = db.start_game()

    service = [s for s in db.services() if s['type'] == 'NORMAL'][0]
    service_id = service['id']

    test_pcap = open('./test/test.pcap', 'rb').read()
    bad_pcap = open('./test/bad.pcap', 'rb').read()
    bad_pcap2 = open('./test/bad2.pcap', 'rb').read()

    with Patcher() as patcher:
        patcher.fs.create_file(f"/pcap/1/{service_id}/new/test.pcap", contents=test_pcap)
        patcher.fs.create_dir(f"/pcap/1/{service_id}/released")
        patcher.fs.create_dir(f"/pcap/1/{service_id}/old")
        patcher.fs.create_dir(f"/pcap/1/{service_id}/processed")

        prior_events = db.events()
        pcapbot.main(db, max_ticks=1)
        after_events = db.events()
        assert not os.path.exists(f"/pcap/1/{service_id}/new/test.pcap")
        assert not os.path.exists(f"/pcap/1/{service_id}/released/test_release.pcap")
        assert os.path.exists(f"/pcap/1/{service_id}/old/test.pcap")
        assert os.path.exists(f"/pcap/1/{service_id}/processed/test_anon.pcap")

        assert open(f"/pcap/1/{service_id}/old/test.pcap", 'rb').read() == test_pcap

        assert len(prior_events) < len(after_events)

        # Release pcaps for the service, submit a new one, and check that it is processed

        response = db.test_client.post(f"/api/v1/service/{service_id}/release_pcaps/1")
        assert response.status_code == 200

        db.new_tick()

        patcher.fs.create_file(f"/pcap/1/{service_id}/new/test2.pcap", contents=test_pcap)
        pcapbot.main(db, max_ticks=1)
        assert not os.path.exists(f"/pcap/1/{service_id}/new/test2.pcap")
        assert os.path.exists(f"/pcap/1/{service_id}/released/test2_release.pcap")
        assert os.path.exists(f"/pcap/1/{service_id}/old/test2.pcap")
        assert os.path.exists(f"/pcap/1/{service_id}/processed/test2_anon.pcap")

        f = open(f"/pcap/1/{service_id}/released/test2_release.pcap", 'rb')
        released_content = f.read()
        f.close()
        assert released_content != test_pcap

        assert released_content == open(f"/pcap/1/{service_id}/processed/test2_anon.pcap", 'rb').read()

        # validate the anonymization of the pcaps
        check_anonymization(released_content, set(['192.168.88.142', '10.1.8.5']), set(['10.13.37.1']))

        # Check that we can process pcaps with invalid data
        patcher.fs.create_file(f"/pcap/1/{service_id}/new/test3.pcap", contents=bad_pcap)
        pcapbot.main(db, max_ticks=1)
        assert not os.path.exists(f"/pcap/1/{service_id}/new/test3.pcap")
        assert os.path.exists(f"/pcap/1/{service_id}/released/test3_release.pcap")
        assert os.path.exists(f"/pcap/1/{service_id}/old/test3.pcap")
        assert os.path.exists(f"/pcap/1/{service_id}/processed/test3_anon.pcap")

        # this is not a valid pcap file, just test that we don't blow up
        patcher.fs.create_file(f"/pcap/1/{service_id}/new/test4pcap", contents=bad_pcap2)
        pcapbot.main(db, max_ticks=1)

        # this is for a team that doesn't exist
        patcher.fs.create_file(f"/pcap/100/{service_id}/new/test.pcap", contents=test_pcap)
        pcapbot.main(db, max_ticks=1)
        assert not os.path.exists(f"/pcap/100/{service_id}/new/test.pcap")


def test_check_structure():
    db = Db("", True)

    start_game = db.start_game()

    with Patcher() as patcher:
        for t in db.teams():
            for s in db.services():
                patcher.fs.create_dir(f"/pcap/{t['id']}/{s['id']}/new")
                patcher.fs.create_dir(f"/pcap/{t['id']}/{s['id']}/released")
                patcher.fs.create_dir(f"/pcap/{t['id']}/{s['id']}/old")
                patcher.fs.create_dir(f"/pcap/{t['id']}/{s['id']}/processed")                
        pcapbot.check_structure("/pcap", db.services(), db.teams())

def test_stealth_parsing():
    db = Db("", True)

    start_game = db.start_game()
    stealth_pcap = open('./test/test_stealth.pcap', 'rb').read()

    # make sure there are stealth attacks here

    pcap_reader = dpkt.pcap.Reader(io.BytesIO(stealth_pcap))
    assert any(
        (dpkt.ethernet.Ethernet(buf).data.data.dport >= 10000 and dpkt.ethernet.Ethernet(buf).data.data.dport <= 20000)
        for _, buf in pcap_reader
    )

    with Patcher() as patcher:
        patcher.fs.create_file('/test.pcap', contents=stealth_pcap)
        success, stealth_events = pcapbot.anonymize_pcap('/test.pcap', 'anon.pcap', '10.13.37.5')
        assert success
        assert len(stealth_events) == 152
        assert set(s[0] for s in stealth_events) == { '10.1.117.100', '10.1.116.100' }

        filtered_pcap = open('anon.pcap', 'rb').read()
        pcap_reader = dpkt.pcap.Reader(io.BytesIO(filtered_pcap))
        assert not any(
            (
                (dpkt.ethernet.Ethernet(buf).data.data.dport >= 10000 and dpkt.ethernet.Ethernet(buf).data.data.dport < 20000) or
                (dpkt.ethernet.Ethernet(buf).data.data.sport >= 10000 and dpkt.ethernet.Ethernet(buf).data.data.sport < 20000)
            ) for _, buf in pcap_reader
        )

def test_stealth_events():
    db = Db("", True)

    stealth_pcap = open('./test/test_stealth.pcap', 'rb').read()
    num_packets = len(list(dpkt.pcap.Reader(io.BytesIO(stealth_pcap))))

    db.start_game()
    service = [s for s in db.services() if s['type'] == 'NORMAL'][0]
    service_id = service['id']

    start_time = time.time()

    with Patcher() as patcher:
        patcher.fs.create_dir(f"/pcap/5/{service_id}/new")
        patcher.fs.create_dir(f"/pcap/5/{service_id}/released")
        patcher.fs.create_dir(f"/pcap/5/{service_id}/old")
        patcher.fs.create_dir(f"/pcap/5/{service_id}/processed")

        # re-time the packets for most of a game of several ticks spread over 25 seconds
        writer = dpkt.pcap.Writer(open(f"/pcap/5/{service_id}/new/test.pcap", 'wb'))
        reader = dpkt.pcap.Reader(io.BytesIO(stealth_pcap))
        for n,(_,buf) in enumerate(reader):
            writer.writepkt(buf, start_time + 20*(n/num_packets))
        writer.close()

        num_timestamped_packets = len(list(dpkt.pcap.Reader(open(f"/pcap/5/{service_id}/new/test.pcap", 'rb'))))
        assert num_timestamped_packets == num_packets

        # make some ticks
        for _ in range(5):
            time.sleep(5)
            db.new_tick()

        prior_events = db.events()
        pcapbot.main(db, max_ticks=1, stealth_report_frequency=2)
        after_events = db.events()

        num_anon_packets = len(list(dpkt.pcap.Reader(open(f"/pcap/5/{service_id}/processed/test_anon.pcap", 'rb'))))
        assert num_anon_packets + 152 == num_packets

        # make sure we have stealth events in every tick of the first 20 seconds
        assert len(prior_events) < len(after_events)
        assert set(e['tick_id'] for e in after_events if e['event_type'] == 'STEALTH') == { 1,2,3,4 }
        assert set(e['dst_team_id'] for e in after_events if e['event_type'] == 'STEALTH') == { 5 }
        assert set(e['src_team_id'] for e in after_events if e['event_type'] == 'STEALTH') == { 16, 17 }
