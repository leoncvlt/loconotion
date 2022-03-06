import os
import sys

import modules.main as main

if __name__ == "__main__":
    try:
        args = main.get_args()
        log = main.setup_logging(args)
        parser = main.init_parser(args, log)
        parser.run()
    except KeyboardInterrupt:
        log.critical("Interrupted by user")
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
