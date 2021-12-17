import logging
import os
import platform

log = logging.getLogger(f"loconotion.{__name__}")
all_files = []
old_to_new = {}
sep = os.path.sep

def process_folder():
    log.info("Processing folder"+ os.getcwd())
    structure = {'assets'+sep+'images': ['png', 'jpg', 'jpeg','bmp','gif','ico'],
                 'assets'+sep+'fonts': ['woff','ttf'],
                 'assets'+sep+'css': ['css'],
                 'assets'+sep+'js': ['js']}
    # !! changing this structure, may break other stuff.

    mapping = {}
    for folder, extensions in structure.items():
        for ext in extensions:
            mapping[ext] = folder

    all_files = os.listdir()
    log.info("Found following files in "+ os.getcwd())
    log.info(all_files)
    for file in all_files:
        ext = file.split('.')[-1]
        new_parent_dir = mapping.get(ext)

        if new_parent_dir:
            new_file = os.path.join(new_parent_dir, file)

            if not os.path.isdir(new_parent_dir):
                os.makedirs(new_parent_dir)

            os.rename(file, new_file)
            old_to_new[file] = new_file
            log.info('%s moved to %s', file, new_file)


def update_code(file_name, old_to_new):
    log.info('Updating assets link in ' + file_name)
    with open(file_name, 'r', encoding = "utf8") as file:
        content = file.read()

    for old, new in old_to_new.items():
        if file_name.endswith('.css'):
            new = new.replace('assets', '..')
            # relative position of files related to css files
        content = content.replace(old, new)

    with open(file_name, 'w') as file:
        file.write(content)


def main():
    process_folder()
    for file in os.listdir():
        if file.endswith('.html'):
            update_code(file, old_to_new)
    for file in os.listdir('assets'+sep+'css'):
        if file.endswith('.css'):
            update_code('assets'+sep+'css'+sep+f'{file}', old_to_new)


def organize(dist_folder):
    os.chdir(dist_folder)

    log.info('Organizing files in assets folder')
    input(
        'Organizer will run in ['+ os.getcwd() +'] Are you sure you are in a correct directory  ? \n Press [ENTER] to confirm or Ctrl + C to quit')
    main()