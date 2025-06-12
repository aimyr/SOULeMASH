from db import waiting_users, active_chats


def is_user_waiting(user_id):
    return user_id in waiting_users

def is_user_in_chat(user_id):
    return user_id in active_chats