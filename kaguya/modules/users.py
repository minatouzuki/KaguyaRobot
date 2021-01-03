from io import BytesIO
from time import sleep
from typing import Optional

from telegram import TelegramError
from telegram.error import BadRequest
from telegram.ext import MessageHandler, Filters, CommandHandler

import perry.modules.sql.users_sql as sql
from perry import dispatcher, OWNER_ID, LOGGER
from perry.modules.helper_funcs.filters import CustomFilters

USERS_GROUP = 4
CHAT_GROUP = 10


def get_user_id(username):
    # ensure valid userid
    if len(username) <= 5:
        return None

    if username.startswith("@"):
        username = username[1:]

    users = sql.get_userid_by_name(username)

    if not users:
        return None

    elif len(users) == 1:
        return users[0].user_id

    else:
        for user_obj in users:
            try:
                userdat = dispatcher.bot.get_chat(user_obj.user_id)
                if userdat.username == username:
                    return userdat.id

            except BadRequest as excp:
                if excp.message == "Chat not found":
                    pass
                else:
                    LOGGER.exception("Error extracting user ID")

    return None


def broadcast(update, context):
    to_send = update.effective_message.text.split(None, 1)
    if len(to_send) >= 2:
        chats = sql.get_all_chats() or []
        failed = 0
        for chat in chats:
            try:
                context.bot.sendMessage(int(chat.chat_id), to_send[1])
                sleep(0.1)
            except TelegramError:
                failed += 1
                LOGGER.warning(
                    "Couldn't send broadcast to %s, group name %s",
                    str(chat.chat_id),
                    str(chat.chat_name),
                )

        update.effective_message.reply_text(
            "Broadcast complete. {} groups failed to receive the message, probably "
            "due to being kicked.".format(failed)
        )


def log_user(update, context):
    chat = update.effective_chat
    msg = update.effective_message

    sql.update_user(
        msg.from_user.id, msg.from_user.username, chat.id, chat.title
    )

    if msg.reply_to_message:
        sql.update_user(
            msg.reply_to_message.from_user.id,
            msg.reply_to_message.from_user.username,
            chat.id,
            chat.title,
        )

    if msg.forward_from:
        sql.update_user(msg.forward_from.id, msg.forward_from.username)


def chats(update, context):
    all_chats = sql.get_all_chats() or []
    chatfile = "List of chats.\n"
    for chat in all_chats:
        chatfile += "{} - ({})\n".format(chat.chat_name, chat.chat_id)

    with BytesIO(str.encode(chatfile)) as output:
        output.name = "chatlist.txt"
        update.effective_message.reply_document(
            document=output,
            filename="chatlist.txt",
            caption="Here is the list of chats in my database.",
        )


def chat_checker(update, context):
    if (
        update.effective_message.chat.get_member(
            context.bot.id
        ).can_send_messages
        is False
    ):
        context.bot.leaveChat(update.effective_message.chat.id)


def __user_info__(user_id):
    if user_id == dispatcher.bot.id:
        return """I've seen them in... Wow. Are they stalking me? They're in all the same places I am... oh. It's me."""
    num_chats = sql.get_user_num_chats(user_id)
    return """I've seen them in <code>{}</code> chats in total.""".format(
        num_chats
    )


def __stats__():
    return "× {} users, across {} chats".format(
        sql.num_users(), sql.num_chats()
    )


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


__help__ = ""  # no help string

__mod_name__ = "Users"

BROADCAST_HANDLER = CommandHandler(
    "broadcast", broadcast, filters=Filters.user(OWNER_ID)
)
USER_HANDLER = MessageHandler(Filters.all & Filters.group, log_user)
CHATLIST_HANDLER = CommandHandler(
    "chatlist", chats, filters=CustomFilters.sudo_filter
)
CHAT_CHECKER_HANDLER = MessageHandler(
    Filters.all & Filters.group, chat_checker
)

dispatcher.add_handler(USER_HANDLER, USERS_GROUP)
dispatcher.add_handler(BROADCAST_HANDLER)
dispatcher.add_handler(CHATLIST_HANDLER)
dispatcher.add_handler(CHAT_CHECKER_HANDLER, CHAT_GROUP)
