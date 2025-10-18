import argparse

from custom_components.vandcentersyd import VandCenterAPI


def main():
    api = VandCenterAPI("", s)
    api.authenticate()

    ret = api.get_data_to()
    print(ret)

if __name__ == "__main__":
    main()
