from functools import wraps
from kaguya.modules.helper_funcs.misc import is_module_loaded

FILENAME = __name__.rsplit(".", 1)[-1]

if is_module_loaded(FILENAME):
    from telegram import Bot, ParseMode, Message
    from telegram.error import BadRequest, Unauthorized
    from telegram.ext import CommandHandler
    from telegram.utils.helpers import escape_markdown

    from kaguya import dispatcher, LOGGER
    from kaguya.modules.helper_funcs.chat_status import user_admin
    from kaguya.modules.sql import log_channel_sql as sql

    def loggable(func):
        @wraps(func)
        def log_action(update, context, *args, **kwargs):
            result = func(update, context, *args, **kwargs)
            chat = update.effective_chat  # type: Optional[Chat]
            message = update.effective_message  # type: Optional[Message]
            if result:
                if chat.type == chat.SUPERGROUP and chat.username:
                    result += (
                        "\n<b>Link:</b> "
                        '<a href="http://telegram.me/{}/{}">click here</a>'.format(
                            chat.username, message.message_id
                        )
                    )
                log_chat = sql.get_chat_log_channel(chat.id)
                if log_chat:
                    try:
                        send_log(context.bot, log_chat, chat.id, result)
                    except Unauthorized:
                        sql.stop_chat_logging(chat.id)

            elif result == "":
                pass
            else:
                LOGGER.warning(
                    "%s was set as loggable, but had no return statement.",
                    func,
                )

            return result

        return log_action

    def send_log(bot: Bot, log_chat_id: str, orig_chat_id: str, result: str):
        try:
            bot.send_message(log_chat_id, result, parse_mode=ParseMode.HTML)
        except BadRequest as excp:
            if excp.message == "Chat not found":
                bot.send_message(
                    orig_chat_id,
                    "This log channel has been deleted - unsetting.",
                )
                sql.stop_chat_logging(orig_chat_id)
            else:
                LOGGER.warning(excp.message)
                LOGGER.warning(result)
                LOGGER.exception("Could not parse")

                bot.send_message(
                    log_chat_id,
                    result
                    + "\n\nFormatting has been disabled due to an unexpected error.",
                )

    @user_admin
    def logging(update, context):
        message = update.effective_message  # type: Optional[Message]
        chat = update.effective_chat  # type: Optional[Chat]

        log_channel = sql.get_chat_log_channel(chat.id)
        if log_channel:
            log_channel_info = context.bot.get_chat(log_channel)
            message.reply_text(
                "This group has all it's logs sent to: {} (`{}`)".format(
                    escape_markdown(log_channel_info.title), log_channel
                ),
                parse_mode=ParseMode.MARKDOWN,
            )

        else:
            message.reply_text("No log channel has been set for this group!")

    @user_admin
    def setlog(update, context):
        message = update.effective_message  # type: Optional[Message]
        chat = update.effective_chat  # type: Optional[Chat]
        if chat.type == chat.CHANNEL:
            message.reply_text(
                "Now, forward the /setlog to the group you want to tie this channel to!"
            )

        elif message.forward_from_chat:
            sql.set_chat_log_channel(chat.id, message.forward_from_chat.id)
            try:
                message.delete()
            except BadRequest as excp:
                if excp.message == "Message to delete not found":
                    pass
                else:
                    LOGGER.exception(
                        "Error deleting message in log channel. Should work anyway though."
                    )

            try:
                context.bot.send_message(
                    message.forward_from_chat.id,
                    "This channel has been set as the log channel for {}.".format(
                        chat.title or chat.first_name
                    ),
                )
            except Unauthorized as excp:
                if (
                    excp.message
                    == "Forbidden: bot is not a member of the channel chat"
                ):
                    context.bot.send_message(
                        chat.id, "Successfully set log channel!"
                    )
                else:
                    LOGGER.exception("ERROR in setting the log channel.")

            context.bot.send_message(chat.id, "Successfully set log channel!")

        else:
            message.reply_text(
                "The steps to set a log channel are:\n"
                " - add bot to the desired channel\n"
                " - send /setlog to the channel\n"
                " - forward the /setlog to the group\n"
            )

    @user_admin
    def unsetlog(update, context):
        message = update.effective_message  # type: Optional[Message]
        chat = update.effective_chat  # type: Optional[Chat]

        log_channel = sql.stop_chat_logging(chat.id)
        if log_channel:
            context.bot.send_message(
                log_channel,
                "Channel has been unlinked from {}".format(chat.title),
            )
            message.reply_text("Log channel has been un-set.")

        else:
            message.reply_text("No log channel has been set yet!")

    def __stats__():
        return "× {} log channels have been set.".format(sql.num_logchannels())

    def __migrate__(old_chat_id, new_chat_id):
        sql.migrate_chat(old_chat_id, new_chat_id)

    def __chat_settings__(chat_id, user_id):
        log_channel = sql.get_chat_log_channel(chat_id)
        if log_channel:
            log_channel_info = dispatcher.bot.get_chat(log_channel)
            return "This group has all it's logs sent to: {} (`{}`)".format(
                escape_markdown(log_channel_info.title), log_channel
            )
        return "No log channel is set for this group!"

    __help__ = """
Recent actions are nice, but they don't help you log every action taken by the bot. This is why you need log channels!

Log channels can help you keep track of exactly what the other admins are doing. \
Bans, Mutes, warns, notes - everything can be moderated.

*Admin only:*
× /logchannel: Get log channel info
× /setlog: Set the log channel.
× /unsetlog: Unset the log channel.

Setting the log channel is done by:
× Add the bot to your channel, as an admin. This is done via the "add administrators" tab.
× Send /setlog to your channel.
× Forward the /setlog command to the group you wish to be logged.
× Congratulations! All is set!
"""

    __mod_name__ = "Logger"

    LOG_HANDLER = CommandHandler("logchannel", logging)
    SET_LOG_HANDLER = CommandHandler("setlog", setlog)
    UNSET_LOG_HANDLER = CommandHandler("unsetlog", unsetlog)

    dispatcher.add_handler(LOG_HANDLER)
    dispatcher.add_handler(SET_LOG_HANDLER)
    dispatcher.add_handler(UNSET_LOG_HANDLER)

else:
    # run anyway if module not loaded
    def loggable(func):
        return func
