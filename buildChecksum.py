import hashlib
import os

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

output = []
for name in sorted(os.listdir('.')):
    if name in ('checksum', os.path.basename(__file__)):
        continue
    if os.path.isfile(name):
        output.append(f"{name}:{sha256(name)}")

with open('checksum', 'w') as f:
    f.write('\n'.join(output))