import os


def patch(base_folder):
    """
    patch table alignment
    """
    for file in os.listdir(base_folder):
        if file.endswith('.html'):
            with open(base_folder + '/' + file, 'r') as f:
                html = f.read()
                html = html.replace('<div style="padding-left: 601px; padding-right: 601px;">', '<div>')
            with open(base_folder + '/' + file, 'w') as f:
                f.write(html)
