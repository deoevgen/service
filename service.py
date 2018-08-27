#!/usr/bin/env python3
from http.server import HTTPServer
from http.server import BaseHTTPRequestHandler
from http import HTTPStatus
import configparser
import argparse
import subprocess as sp
from time import sleep
import os
import sys

process = list()


class HttpProcessor(BaseHTTPRequestHandler):

    def do_GET(self):
        print(self.path)

        if self.path == '/v1/start':
            self.start()

        if self.path == '/v1/stop':
            self.stop()

        self.send_response(HTTPStatus.ACCEPTED)
        self.end_headers()

        self.wfile.write(b'hello_1')

    @staticmethod
    def start():
        #  TODO: решить проблемы с внутренней переменной, как ее пропихнуть сюда без нового объекта Service
        app = Service()
        proc = sp.Popen([app.get_app()],
                           stdout=sp.PIPE,
                           stdin=sp.PIPE,
                           stderr=sp.PIPE)
        sleep(1)
        print(proc.pid)
        if proc.poll() is None:
            print(proc.poll())
            process.append(proc)
            return
        proc.kill()
        return

    @staticmethod
    def stop():
        for proc in process:
            proc.kill()
            sleep(1)
            print(proc.poll())
            if proc.poll() is None:
                print('Процесс не завершился!', proc.pid)


class Service:
    def __init__(self):
        config = configparser.ConfigParser()
        config_path = os.path.dirname(sys.argv[0])
        config.read(os.path.join(config_path, 'config.ini'))

        # порт прложения, берется из аргумента при запуске программы
        self.port = None

        # информация о контроллере, куда отпарвлять данные
        ip = config.get('georg', 'ip')
        port = config.get('georg', 'port')
        self.server = '{ip}:{port}'.format(ip=ip, port=port)
        # имя приложения, для контроллера
        self.name = config.get('app', 'name')
        self.app = config.get('app', 'path')

    def set_port(self, port):
        self.port = port

    def start_app(self):

        app_address = ("localhost", self.port)
        # запуск приложения
        try:
            httpd = HTTPServer(app_address, HttpProcessor)
            httpd.serve_forever()
        except OSError as e:
            return e.strerror
        except:
            return b'Error not found'

    def get_app(self):
        return self.app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', action='store', dest='port', help='Port', type=int)
    args = parser.parse_args()

    if not args.port:
        print('Укажите порт -p для корректной работы')
        return

    session = Service()
    session.set_port(args.port)
    session.start_app()


if __name__ == '__main__':
    main()
