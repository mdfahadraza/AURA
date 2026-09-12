def write_file(filename, content):
    with open(filename, "w") as f:
        f.write(content)
    return f"File {filename} written successfully"
