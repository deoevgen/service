from service import Service
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', action='store', dest='port', help='Port', type=int)
    args = parser.parse_args()

    if not args.port:
        print('Укажите порт -p для корректной работы')
        return

    service = Service()
    service.start()
    service.join()


if __name__ == '__main__':
    main()
