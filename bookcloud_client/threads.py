import logging
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import json
from urllib.parse import urlparse

import netifaces
import requests
import tqdm
from fido2 import cbor
from fido2.client import Fido2Client
from fido2.hid import CtapHidDevice
from fido2.utils import websafe_encode
from pyomxplayer import OMXPlayer

AUTHENTICATE_BEGIN_URI = 'https://console.bookcloud.com.tw/rpi/api/authenticate_begin?rpi_username={}'
AUTHENTICATE_COMPLETE_URI = 'https://console.bookcloud.com.tw/rpi/api/authenticate_complete?rpi_username={}'
HEARTBEAT_URI = 'https://console.bookcloud.com.tw/rpi/api/status_update'


def create_fido2_client(origin):
    dev = next(CtapHidDevice.list_devices(), None)
    assert dev
    client = Fido2Client(dev, origin)
    return client


def get_access_key(rpi_username, verify=True, uv=False):
    auth_begin_response = requests.request('GET', AUTHENTICATE_BEGIN_URI.format(rpi_username), verify=verify)
    assert auth_begin_response.status_code == 200
    cookies = auth_begin_response.cookies
    auth_begin_response_dict = cbor.decode(auth_begin_response.content)
    urlparse_result = urlparse(AUTHENTICATE_BEGIN_URI)
    scheme = urlparse_result.scheme
    origin = urlparse_result.hostname
    rp_id = auth_begin_response_dict['publicKey']['rpId']
    challenge = websafe_encode(auth_begin_response_dict['publicKey']['challenge'])
    allow_list = auth_begin_response_dict['publicKey']['allowCredentials']
    fido2_client = create_fido2_client('{}://{}'.format(scheme, origin))
    assertions, client_data = fido2_client.get_assertion(rp_id, challenge, allow_list, uv=uv)
    access_key = websafe_encode(assertions[0].signature)
    auth_complete_payload = dict(
        credentialId=assertions[0].credential['id'],
        clientDataJSON=client_data,
        authenticatorData=assertions[0].auth_data,
        signature=assertions[0].signature,
    )
    auth_complete_payload_encoded = cbor.encode(auth_complete_payload)
    auth_complete_response = requests.post(
        AUTHENTICATE_COMPLETE_URI.format(rpi_username),
        data=auth_complete_payload_encoded,
        verify=verify, cookies=cookies,
    )
    auth_complete_response_decoded = cbor.decode(auth_complete_response.content)
    assert auth_complete_response_decoded.get('status') == 'OK'
    return access_key


class ThreadHeartbeat(threading.Thread):
    def __init__(self, access_key, player_queue, downloading_queue, heartbeat_uri=HEARTBEAT_URI, *args, **kwargs):
        self.player_queue = player_queue
        self.heartbeat_uri = heartbeat_uri
        self.downloading_queue = downloading_queue
        self.access_key = access_key
        super(ThreadHeartbeat, self).__init__(*args, **kwargs)

    @staticmethod
    def get_git_version():
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('utf-8').strip()

    @staticmethod
    def get_ip():
        ip_dict = dict()
        for interface_name in netifaces.interfaces():
            addresses = [
                i['addr'] for i in netifaces.ifaddresses(interface_name).setdefault(netifaces.AF_INET, [{'addr': None}])
            ]
            ip_dict[interface_name] = addresses

        return ip_dict

    @staticmethod
    def get_teamviewer_no():
        output = subprocess.check_output(['teamviewer', 'info']).decode('utf-8')
        tv_str = output[output.find('TeamViewer ID:') + len('TeamViewer ID:'):].strip().split()[-1]
        if not tv_str.isdigit():
            tv_str = output[output.find('TeamViewer ID:') + len('TeamViewer ID:'):].split('\n')[0].split()[-1]

        if tv_str.isdigit():
            return tv_str
        else:
            raise Exception('Parsing error: {}'.format(tv_str))

    @staticmethod
    def get_temperature():
        output = subprocess.check_output(['/opt/vc/bin/vcgencmd', 'measure_temp']).decode('utf-8')
        temperature = output.strip().strip('temp=').strip('\'C')
        return temperature

    @staticmethod
    def test_self_connect():
        try:
            requests.get('http://127.0.0.1:8000')
            return True
        except Exception as e:
            logging.exception(e)
            return False

    def get_download_status(self):
        data = {}
        try:
            downloading_thread = self.downloading_queue.get_nowait()
            data.update(downloading_thread.progress_bar.format_dict)
            self.downloading_queue.put(downloading_thread)
            self.downloading_queue.task_done()
        except queue.Empty:
            pass
        return data

    def run(self):
        time.sleep(5)
        if not self.test_self_connect():
            logging.critical('Exception happened when self connecting.')
            logging.critical('Restarting services...')
            os.kill(os.getpid(), signal.SIGKILL)
            sys.exit(1)

        while True:
            short_sleep = False
            try:
                data = {}
                try:
                    data['tv_no'] = self.get_teamviewer_no()
                except Exception:
                    pass

                try:
                    data['ip_addr'] = self.get_ip()
                except Exception:
                    pass

                try:
                    data['version'] = self.get_git_version()
                except Exception:
                    pass

                try:
                    data['temperature'] = self.get_temperature()
                except Exception:
                    pass

                try:
                    omx = self.player_queue.get_nowait()
                    data['player'] = omx.__dict__.copy()
                    for each in list(data['player'].keys()):
                        if each.startswith('_'):
                            del data['player'][each]
                        if each == 'parser':
                            del data['player'][each]
                    if type(data.get('player', {}).get('audio', {}).get('decoder')) == bytes:
                        data['player']['audio']['decoder'] = data['player']['audio']['decoder'].decode()
                    if type(data.get('player', {}).get('video', {}).get('decoder')) == bytes:
                        data['player']['video']['decoder'] = data['player']['video']['decoder'].decode()
                except queue.Empty:
                    omx = None
                except Exception as e:
                    logging.exception(e)
                finally:
                    if omx:
                        self.player_queue.put(omx)

                try:
                    data['downloading'] = self.get_download_status()
                except Exception as e:
                    logging.exception(e)

                requests.post(self.heartbeat_uri, data={'data': json.dumps(data), 'access_key': self.access_key})
            except Exception as e:
                logging.exception(e)
                short_sleep = True

            if short_sleep:
                time.sleep(5)
            else:
                time.sleep(60)


class ThreadCommand(threading.Thread):
    def __init__(self, command_queue, playlist_queue, player_queue, download_queue, downloading_queue):
        self.command_queue = command_queue
        self.player_queue = player_queue
        self.playlist_queue = playlist_queue
        self.download_queue = download_queue
        self.downloading_queue = downloading_queue
        threading.Thread.__init__(self)

    @staticmethod
    def empty_queue(target_queue):
        try:
            target_queue.get_nowait()
            target_queue.task_done()
        except Exception as e:
            logging.info(e)

    @staticmethod
    def update():
        subprocess.call(['git', 'checkout', '--', '.'], shell=False)
        subprocess.call(['git', 'pull'], shell=False)
        subprocess.call(['chmod', 'u+x', './boot.sh'])

    def run(self):
        while True:
            cmd = self.command_queue.get()
            if cmd not in ['reboot', 'update']:
                try:
                    omx = self.player_queue.get(timeout=3)
                except queue.Empty:
                    omx = None
            else:
                omx = None

            try:
                if cmd == 'pause' and omx:
                    omx.toggle_pause()
                elif cmd == 'next' and omx:
                    if not self.playlist_queue.empty():
                        omx.stop()  # Stop playing cause playlist thread push another video in
                elif cmd == 'stop':
                    self.empty_queue(self.playlist_queue)
                    self.empty_queue(self.download_queue)
                    try:
                        downloading_thread = self.downloading_queue.get_nowait()
                        downloading_thread.stop = True
                        self.downloading_queue.put(downloading_thread)
                        self.downloading_queue.task_done()
                    except queue.Empty:
                        pass
                    if omx:
                        omx.stop()
                elif cmd == 'mute' and omx:
                    omx.toggle_mute()
                elif cmd in (
                        'inc_vol', 'dec_vol', 'back_30', 'back_600', 'forward_30', 'forward_600',
                        'inc_speed', 'dec_speed',
                ) and omx:
                    func = getattr(omx, cmd)
                    func()
                elif cmd == 'reboot':
                    subprocess.call(['sudo', 'shutdown', '-r', 'now'], shell=False)
                elif cmd == 'update':
                    self.update()
                else:
                    pass
            except Exception as e:
                logging.exception(e)
            finally:
                if omx:
                    self.player_queue.put(omx)
                    self.player_queue.task_done()
            self.command_queue.task_done()


class ThreadPlayer(threading.Thread):
    def __init__(self, player_queue, path, *args):
        self.player_queue = player_queue
        self.path = path
        self.args = args
        threading.Thread.__init__(self)

    def run(self):
        omx = OMXPlayer(self.path, args=self.args)
        self.player_queue.put(omx)
        omx.toggle_pause()
        last_position = 0
        wait_time = 10
        while True:
            time.sleep(1)
            if not omx.is_running():
                self.player_queue.get()
                self.player_queue.task_done()
                break
            elif not omx.paused and omx.position == last_position:
                wait_time = wait_time - 1
                if wait_time <= 0:
                    omx.stop()
            else:
                last_position = omx.position


class ThreadPlaylist(threading.Thread):
    def __init__(self, playlist_queue, player_queue):
        self.playlist_queue = playlist_queue
        self.player_queue = player_queue
        threading.Thread.__init__(self)

    def run(self):
        while True:
            path = self.playlist_queue.get()
            current_thread = ThreadPlayer(self.player_queue, path)
            current_thread.start()
            current_thread.join()
            self.playlist_queue.task_done()


class ThreadDownloading(threading.Thread):
    def __init__(self, download_url, download_dest=None):
        self.download_url = download_url
        self.download_dest = download_dest
        self.progress_bar = None
        self.stop = False
        super(ThreadDownloading, self).__init__()

    def run(self):
        local_filename = self.download_url.split('/')[-1]
        local_filename = local_filename.split('?')[0]
        if self.download_dest:
            local_filename = '{}/{}'.format(self.download_dest.rstrip('/'), local_filename)
        with requests.get(self.download_url, stream=True) as r:
            with tqdm.tqdm(
                    total=int(r.headers['content-length']),
                    unit='B', unit_scale=True, unit_divisor=1024,
            ) as progress_bar:
                self.progress_bar = progress_bar
                with open(local_filename, 'wb') as f:
                    length = 16 * 1024
                    while 1:
                        buf = r.raw.read(length)
                        if not buf:
                            break
                        f.write(buf)
                        progress_bar.update(length)
                        if self.stop:
                            return


class ThreadDownload(threading.Thread):
    def __init__(self, download_queue, downloading_queue, playlist_queue):
        self.download_queue = download_queue
        self.downloading_queue = downloading_queue
        self.playlist_queue = playlist_queue
        super(ThreadDownload, self).__init__()

    def run(self):
        while True:
            path = self.download_queue.get()
            filename = path.split('/')[-1]
            filename = filename.split('?')[0]
            current_thread = ThreadDownloading(path, download_dest='/tmp/')
            self.downloading_queue.put(current_thread)
            current_thread.start()
            current_thread.join()
            downloading_thread = self.downloading_queue.get(current_thread)
            self.downloading_queue.task_done()
            self.download_queue.task_done()
            if not downloading_thread.stop:
                self.playlist_queue.put('/tmp/{}'.format(filename))
