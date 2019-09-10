from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

import requests
import os
import json

from bookcloud_client.wsgi import command_queue, download_queue


# Create your views here.


def rpi_s3download_handler_view(request):
    come_from = request.POST.get('come_from', request.GET.get('come_from', None))
    response = requests.post(
        'https://console.bookcloud.com.tw/rpi/api/cmd_resolve', data={
            'access_key': os.environ.get('BOOKCLOUD_ACCESS_KEY'),
            'cmd_token': request.GET['cmd_token'],
        },
    )

    resposne_json = json.loads(response.content)
    for each in resposne_json['data']['download_link']:
        download_queue.put(each)
    return redirect(come_from)


@csrf_exempt
def rpi_command_handler_view(request):
    come_from = request.POST.get('come_from', request.GET.get('come_from', None))
    command = request.POST.get('command', request.GET.get('command', None))
    if not command:
        message = 'No command offered'
    else:
        command_queue.put(command)
        message = 'Succcess'
    if come_from:
        if '?' in come_from:
            return redirect(come_from + '&message={}'.format(message))
        else:
            return redirect(come_from + '?message={}'.format(message))
    else:
        return JsonResponse({'message': message})


def rpi_panel_view(request):
    return render(request, template_name='bookcloud_handler/panel.html')
