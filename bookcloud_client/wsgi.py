"""
WSGI config for bookcloud_client project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/howto/deployment/wsgi/
"""

import os
import queue
import subprocess

from django.core.wsgi import get_wsgi_application

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from . import settings
from . import threads

command_queue = queue.Queue()
playlist_queue = queue.Queue()
player_queue = queue.Queue()
download_queue = queue.Queue()
downloading_queue = queue.Queue()

settings.COMMAND_QUEUE = command_queue
settings.playlist_queue = playlist_queue
settings.player_queue = player_queue
settings.download_queue = download_queue
settings.downloading_queue = downloading_queue

web_driver_options = Options()
web_driver_options.add_argument('--kiosk')
web_driver_options.add_argument('--disable-infobars')
web_driver_options.add_argument('--noerrdialogs')

web_driver = webdriver.Chrome(options=web_driver_options)

web_driver.get('file:///home/pi/bookcloud_client/assets/security_key.png')

try:
    access_key = threads.get_access_key('rpitv_1381633462')
except Exception as e:
    raise

web_driver.get('https://via.placeholder.com/1920x1080.png?text=Here we Go')

download_thread = threads.ThreadDownload(download_queue, downloading_queue, playlist_queue)
playlist_thread = threads.ThreadPlaylist(playlist_queue, player_queue)
command_thread = threads.ThreadCommand(command_queue, playlist_queue, player_queue, download_queue, downloading_queue)
heartbeat_thread = threads.ThreadHeartbeat(access_key, player_queue, downloading_queue)

settings.download_thread = download_thread
settings.playlist_thread = playlist_thread
settings.command_thread = command_thread
settings.heartbeat_thread = heartbeat_thread

os.environ.setdefault('BOOKCLOUD_ACCESS_KEY', access_key)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings)

application = get_wsgi_application()

download_thread.start()
playlist_thread.start()
command_thread.start()
heartbeat_thread.start()
