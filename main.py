"""Точка входа: python main.py [--region | --full | --settings]"""
import sys

from kadr.app import main

if __name__ == "__main__":
    sys.exit(main())
