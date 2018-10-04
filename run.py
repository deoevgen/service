from service import Service


def main():
    service = Service()
    service.start()
    service.join()


if __name__ == '__main__':
    main()
