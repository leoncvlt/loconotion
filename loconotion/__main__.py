import os
import sys

import modules.main as main

def _exit():
    try:
        sys.exit(1)
    except SystemExit:
        os._exit(1)

if __name__ == "__main__":
    try:
        args = main.get_args()
        log = main.setup_logging(args)
        parser = main.init_parser(args, log)
        parser.run()
    except KeyboardInterrupt:
        log.critical("Interrupted by user")
        _exit()
    except Exception as ex:
        if args.verbose:
            log.exception(ex)
        else:
            log.critical(f"{ex.__class__.__name__}: {str(ex)}")
        _exit()
