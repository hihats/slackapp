import json

with open('/mnt/user-data/uploads/cleard_users.json') as f:
    data = json.load(f)

result = [
    {'user_name': item['user_name'], 'user_real_name': item['user_real_name']}
    for item in data['items']
]

with open('/mnt/user-data/outputs/users_name_only.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
