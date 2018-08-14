#!/usr/bin/env python3
from http.server import HTTPServer
from http.server import BaseHTTPRequestHandler
from http import HTTPStatus
import configparser
import argparse


config = configparser.ConfigParser()
config.read('config.ini')


class HttpProcessor(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(HTTPStatus.ACCEPTED)
        self.end_headers()
        self.wfile.write(b'hello_1')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', action='store', dest='port', help='Port', type=int)
    args = parser.parse_args()

    if not args.port:
        print('Укажите порт для корректной работы')
        return

    server_address = ("localhost", args.port)


    # запуск приложения
    try:
        httpd = HTTPServer(server_address, HttpProcessor)
    except OSError as e:
        print(e.strerror)
        return
    except:
        print(b'Error not found')
        return

    print(server_address)
    httpd.serve_forever()


if __name__ == '__main__':
    main()
