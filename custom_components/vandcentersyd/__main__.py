import argparse

from custom_components.vandcentersyd import VandCenterAPI


def main():
    s = 't2TEQm\\."@Y4aAf#=b;s\'kLM7V#U'

    api = VandCenterAPI("peter@pratgen.dk", s)
    api.authenticate()

    ret = api.get_data_to()
    print(ret)

if __name__ == "__main__":
    main()
