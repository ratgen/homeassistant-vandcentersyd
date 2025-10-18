import argparse
from . import VandCenterAPI


def main():
    parser = argparse.ArgumentParser("pyeforsyning")
    parser.add_argument("--username", action="store", required=False)
    parser.add_argument("--password", action="store", required=True)

    args = parser.parse_args()

    username = args.username
    password = args.password

    api = VandCenterAPI(username, password)
    api.authenticate()

    api.get_data_to()