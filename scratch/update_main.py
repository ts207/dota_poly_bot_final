import os

path = '/home/irene/dota_poly_bot_final/main.py'
with open(path, 'r') as f:
    content = f.read()

old_line = 'map_num = self.dota_feed.current_map_number'
new_line = 'map_num = int(os.getenv("MAP_NUMBER_OVERRIDE", self.dota_feed.current_map_number))'

if old_line in content:
    content = content.replace(old_line, new_line)
    with open(path, 'w') as f:
        f.write(content)
    print("Successfully updated main.py")
else:
    print("Could not find the target line in main.py")
