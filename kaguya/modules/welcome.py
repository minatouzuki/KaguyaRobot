from html import escape
import time
import re

from telegram import (
    ParseMode,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
    CallbackQuery,
)
from telegram.error import BadRequest
from telegram.ext import (
    MessageHandler,
    Filters,
    CommandHandler,
    CallbackQueryHandler,
)
from telegram.utils.helpers import mention_html

import perry.modules.sql.welcome_sql as sql
from perry.modules.sql.global_bans_sql import is_user_gbanned
from perry import dispatcher, OWNER_ID, LOGGER, MESSAGE_DUMP, spamwtc
from perry.modules.helper_funcs.chat_status import (
    user_admin,
    is_user_ban_protected,
)
from perry.modules.helper_funcs.misc import build_keyboard, revert_buttons
from perry.modules.helper_funcs.msg_types import get_welcome_type
from perry.modules.helper_funcs.alternate import typing_action
from perry.modules.helper_funcs.string_handling import (
    markdown_parser,
    escape_invalid_curly_brackets,
    markdown_to_html,
)
from perry.modules.log_channel import loggable

VALID_WELCOME_FORMATTERS = [
    "first",
    "last",
    "fullname",
    "username",
    "id",
    "count",
    "chatname",
    "mention",
]

ENUM_FUNC_MAP = {
    sql.Types.TEXT.value: dispatcher.bot.send_message,
    sql.Types.BUTTON_TEXT.value: dispatcher.bot.send_message,
    sql.Types.STICKER.value: dispatcher.bot.send_sticker,
    sql.Types.DOCUMENT.value: dispatcher.bot.send_document,
    sql.Types.PHOTO.value: dispatcher.bot.send_photo,
    sql.Types.AUDIO.value: dispatcher.bot.send_audio,
    sql.Types.VOICE.value: dispatcher.bot.send_voice,
    sql.Types.VIDEO.value: dispatcher.bot.send_video,
}


# do not async
def send(update, message, keyboard, backup_message):
    chat = update.effective_chat
    cleanserv = sql.clean_service(chat.id)
    reply = update.message.message_id
    # Clean service welcome
    if cleanserv:
        try:
            dispatcher.bot.delete_message(chat.id, update.message.message_id)
        except BadRequest:
            pass
        reply = False
    try:
        msg = update.effective_message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            reply_to_message_id=reply,
            disable_web_page_preview=True,
        )
    except IndexError:
        msg = update.effective_message.reply_text(
            markdown_parser(
                backup_message + "\nNote: the current message was "
                "invalid due to markdown issues. Could be "
                "due to the user's name."
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_to_message_id=reply,
        )
    except KeyError:
        msg = update.effective_message.reply_text(
            markdown_parser(
                backup_message + "\nNote: the current message is "
                "invalid due to an issue with some misplaced "
                "curly brackets. Please update"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_to_message_id=reply,
        )
    except BadRequest as excp:
        if excp.message == "Button_url_invalid":
            msg = update.effective_message.reply_text(
                markdown_parser(
                    backup_message
                    + "\nNote: the current message has an invalid url "
                    "in one of its buttons. Please update."
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=reply,
            )
        elif excp.message == "Unsupported url protocol":
            msg = update.effective_message.reply_text(
                markdown_parser(
                    backup_message
                    + "\nNote: the current message has buttons which "
                    "use url protocols that are unsupported by "
                    "telegram. Please update."
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=reply,
            )
        elif excp.message == "Wrong url host":
            msg = update.effective_message.reply_text(
                markdown_parser(
                    backup_message
                    + "\nNote: the current message has some bad urls. "
                    "Please update."
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=reply,
            )
            LOGGER.warning(message)
            LOGGER.warning(keyboard)
            LOGGER.exception("Could not parse! got invalid url host errors")
        else:
            msg = update.effective_message.reply_text(
                markdown_parser(
                    backup_message
                    + "\nNote: An error occured when sending the "
                    "custom message. Please update."
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=reply,
            )
            LOGGER.exception()

    return msg


def new_member(update, context):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    chat_name = chat.title or chat.first or chat.username
    should_welc, cust_welcome, welc_type = sql.get_welc_pref(chat.id)
    cust_welcome = markdown_to_html(cust_welcome)
    welc_mutes = sql.welcome_mutes(chat.id)
    user_id = user.id
    human_checks = sql.get_human_checks(user_id, chat.id)
    if should_welc:
        sent = None
        new_members = update.effective_message.new_chat_members
        for new_mem in new_members:

            reply = update.message.message_id
            cleanserv = sql.clean_service(chat.id)
            # Clean service welcome
            if cleanserv:
                try:
                    dispatcher.bot.delete_message(
                        chat.id, update.message.message_id
                    )
                except BadRequest:
                    pass
                reply = False

            # Ignore spamwatch banned users
            try:
                sw = spamwtc.get_ban(int(new_mem.id))
                if sw:
                    return
            except Exception:
                pass

            # Ignore gbanned users
            if is_user_gbanned(new_mem.id):
                return

            # Give the owner a special welcome
            if new_mem.id == OWNER_ID:
                update.effective_message.reply_text(
                    "Master is in the houseeee, let's get this party started!",
                    reply_to_message_id=reply,
                )
                continue

            # Make bot greet admins
            elif new_mem.id == context.bot.id:
                update.effective_message.reply_text(
                    "Hey {}, I'm {}! Thank you for adding me to {}"
                    " and be sure to join our channel: @FinfBotNews to know more about updates and tricks!".format(
                        user.first_name, context.bot.first_name, chat_name
                    ),
                    reply_to_message_id=reply,
                )

                context.bot.send_message(
                    MESSAGE_DUMP,
                    "perry have been added to <pre>{}</pre> with ID: \n<pre>{}</pre>".format(
                        chat.title, chat.id
                    ),
                    parse_mode=ParseMode.HTML,
                )
            else:
                # If welcome message is media, send with appropriate function
                if (
                    welc_type != sql.Types.TEXT
                    and welc_type != sql.Types.BUTTON_TEXT
                ):
                    sent = ENUM_FUNC_MAP[welc_type](chat.id, cust_welcome)
                    # print(bool(sent))
                    continue
                # else, move on
                first_name = (
                    new_mem.first_name or "PersonWithNoName"
                )  # edge case of empty name - occurs for some bugs.

                if cust_welcome:
                    if new_mem.last_name:
                        fullname = "{} {}".format(
                            first_name, new_mem.last_name
                        )
                    else:
                        fullname = first_name
                    count = chat.get_members_count()
                    mention = mention_html(new_mem.id, first_name)
                    if new_mem.username:
                        username = "@" + escape(new_mem.username)
                    else:
                        username = mention

                    valid_format = escape_invalid_curly_brackets(
                        cust_welcome, VALID_WELCOME_FORMATTERS
                    )
                    res = valid_format.format(
                        first=escape(first_name),
                        last=escape(new_mem.last_name or first_name),
                        fullname=escape(fullname),
                        username=username,
                        mention=mention,
                        count=count,
                        chatname=escape(chat.title),
                        id=new_mem.id,
                    )
                    buttons = sql.get_welc_buttons(chat.id)
                    keyb = build_keyboard(buttons)
                else:
                    res = sql.DEFAULT_WELCOME.format(first=first_name)
                    keyb = []

                keyboard = InlineKeyboardMarkup(keyb)

                sent = send(
                    update,
                    res,
                    keyboard,
                    sql.DEFAULT_WELCOME.format(first=first_name),
                )  # type: Optional[Message]

                # User exception from mutes:
                if (
                    is_user_ban_protected(
                        chat, new_mem.id, chat.get_member(new_mem.id)
                    )
                    or human_checks
                ):
                    continue
                # Join welcome: soft mute
                if welc_mutes == "soft":
                    context.bot.restrict_chat_member(
                        chat.id,
                        new_mem.id,
                        permissions=ChatPermissions(
                            can_send_messages=True,
                            can_send_media_messages=False,
                            can_send_other_messages=False,
                            can_invite_users=False,
                            can_pin_messages=False,
                            can_send_polls=False,
                            can_change_info=False,
                            can_add_web_page_previews=False,
                            until_date=(int(time.time() + 24 * 60 * 60)),
                        ),
                    )
                # Join welcome: strong mute
                if welc_mutes == "strong":
                    new_join_mem = "Hey {}!".format(
                        mention_html(user.id, new_mem.first_name)
                    )
                    msg.reply_text(
                        "{}\nClick the button below to start talking.".format(
                            new_join_mem
                        ),
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        text="Yus, I'm a human",
                                        callback_data="user_join_({})".format(
                                            new_mem.id
                                        ),
                                    )
                                ]
                            ]
                        ),
                        parse_mode=ParseMode.HTML,
                        reply_to_message_id=reply,
                    )
                    context.bot.restrict_chat_member(
                        chat.id,
                        new_mem.id,
                        permissions=ChatPermissions(
                            can_send_messages=False,
                            can_invite_users=False,
                            can_pin_messages=False,
                            can_send_polls=False,
                            can_change_info=False,
                            can_send_media_messages=False,
                            can_send_other_messages=False,
                            can_add_web_page_previews=False,
                        ),
                    )
        prev_welc = sql.get_clean_pref(chat.id)
        if prev_welc:
            try:
                context.bot.delete_message(chat.id, prev_welc)
            except BadRequest:
                pass

            if sent:
                sql.set_clean_welcome(chat.id, sent.message_id)


def left_member(update, context):
    chat = update.effective_chat  # type: Optional[Chat]
    should_goodbye, cust_goodbye, goodbye_type = sql.get_gdbye_pref(chat.id)
    cust_goodbye = markdown_to_html(cust_goodbye)
    if should_goodbye:
        reply = update.message.message_id
        cleanserv = sql.clean_service(chat.id)
        # Clean service welcome
        if cleanserv:
            try:
                dispatcher.bot.delete_message(
                    chat.id, update.message.message_id
                )
            except BadRequest:
                pass
            reply = False

        left_mem = update.effective_message.left_chat_member
        if left_mem:

            # Ignore gbanned users
            if is_user_gbanned(left_mem.id):
                return

            # Ignore spamwatch banned users
            try:
                sw = spamwtc.get_ban(int(left_mem.id))
                if sw:
                    return
            except:
                pass

            # Ignore bot being kicked
            if left_mem.id == context.bot.id:
                return

            # Give the owner a special goodbye
            if left_mem.id == OWNER_ID:
                update.effective_message.reply_text(
                    "RIP Master", reply_to_message_id=reply
                )
                return

            # if media goodbye, use appropriate function for it
            if (
                goodbye_type != sql.Types.TEXT
                and goodbye_type != sql.Types.BUTTON_TEXT
            ):
                ENUM_FUNC_MAP[goodbye_type](chat.id, cust_goodbye)
                return

            first_name = (
                left_mem.first_name or "PersonWithNoName"
            )  # edge case of empty name - occurs for some bugs.
            if cust_goodbye:
                if left_mem.last_name:
                    fullname = "{} {}".format(first_name, left_mem.last_name)
                else:
                    fullname = first_name
                count = chat.get_members_count()
                mention = mention_html(left_mem.id, first_name)
                if left_mem.username:
                    username = "@" + escape(left_mem.username)
                else:
                    username = mention

                valid_format = escape_invalid_curly_brackets(
                    cust_goodbye, VALID_WELCOME_FORMATTERS
                )
                res = valid_format.format(
                    first=escape(first_name),
                    last=escape(left_mem.last_name or first_name),
                    fullname=escape(fullname),
                    username=username,
                    mention=mention,
                    count=count,
                    chatname=escape(chat.title),
                    id=left_mem.id,
                )
                buttons = sql.get_gdbye_buttons(chat.id)
                keyb = build_keyboard(buttons)

            else:
                res = sql.DEFAULT_GOODBYE
                keyb = []

            keyboard = InlineKeyboardMarkup(keyb)

            send(update, res, keyboard, sql.DEFAULT_GOODBYE)


@user_admin
@typing_action
def welcome(update, context):
    chat = update.effective_chat  # type: Optional[Chat]
    args = context.args
    # if no args, show current replies.
    if len(args) == 0 or args[0].lower() == "noformat":
        noformat = args and args[0].lower() == "noformat"
        pref, welcome_m, welcome_type = sql.get_welc_pref(chat.id)
        update.effective_message.reply_text(
            "This chat has it's welcome setting set to: `{}`.\n*The welcome message "
            "(not filling the {{}}) is:*".format(pref),
            parse_mode=ParseMode.MARKDOWN,
        )

        if welcome_type == sql.Types.BUTTON_TEXT:
            buttons = sql.get_welc_buttons(chat.id)
            if noformat:
                welcome_m += revert_buttons(buttons)
                update.effective_message.reply_text(welcome_m)

            else:
                keyb = build_keyboard(buttons)
                keyboard = InlineKeyboardMarkup(keyb)

                send(update, welcome_m, keyboard, sql.DEFAULT_WELCOME)

        else:
            if noformat:
                ENUM_FUNC_MAP[welcome_type](chat.id, welcome_m)

            else:
                ENUM_FUNC_MAP[welcome_type](
                    chat.id, welcome_m, parse_mode=ParseMode.MARKDOWN
                )

    elif len(args) >= 1:
        if args[0].lower() in ("on", "yes"):
            sql.set_welc_preference(str(chat.id), True)
            update.effective_message.reply_text("I'll be polite!")

        elif args[0].lower() in ("off", "no"):
            sql.set_welc_preference(str(chat.id), False)
            update.effective_message.reply_text(
                "I'm sulking, not gonna greet anymore."
            )

        else:
            # idek what you're writing, say yes or no
            update.effective_message.reply_text(
                "I understand 'on/yes' or 'off/no' only!"
            )


@user_admin
@typing_action
def goodbye(update, context):
    chat = update.effective_chat  # type: Optional[Chat]
    args = context.args

    if len(args) == 0 or args[0] == "noformat":
        noformat = args and args[0] == "noformat"
        pref, goodbye_m, goodbye_type = sql.get_gdbye_pref(chat.id)
        update.effective_message.reply_text(
            "This chat has it's goodbye setting set to: `{}`.\n*The goodbye  message "
            "(not filling the {{}}) is:*".format(pref),
            parse_mode=ParseMode.MARKDOWN,
        )

        if goodbye_type == sql.Types.BUTTON_TEXT:
            buttons = sql.get_gdbye_buttons(chat.id)
            if noformat:
                goodbye_m += revert_buttons(buttons)
                update.effective_message.reply_text(goodbye_m)

            else:
                keyb = build_keyboard(buttons)
                keyboard = InlineKeyboardMarkup(keyb)

                send(update, goodbye_m, keyboard, sql.DEFAULT_GOODBYE)

        else:
            if noformat:
                ENUM_FUNC_MAP[goodbye_type](chat.id, goodbye_m)

            else:
                ENUM_FUNC_MAP[goodbye_type](
                    chat.id, goodbye_m, parse_mode=ParseMode.MARKDOWN
                )

    elif len(args) >= 1:
        if args[0].lower() in ("on", "yes"):
            sql.set_gdbye_preference(str(chat.id), True)
            update.effective_message.reply_text(
                "I'll be sorry when people leave!"
            )

        elif args[0].lower() in ("off", "no"):
            sql.set_gdbye_preference(str(chat.id), False)
            update.effective_message.reply_text(
                "They leave, they're dead to me."
            )

        else:
            # idek what you're writing, say yes or no
            update.effective_message.reply_text(
                "I understand 'on/yes' or 'off/no' only!"
            )


@user_admin
@loggable
@typing_action
def set_welcome(update, context) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    msg = update.effective_message  # type: Optional[Message]

    text, data_type, content, buttons = get_welcome_type(msg)

    if data_type is None:
        msg.reply_text("You didn't specify what to reply with!")
        return ""

    sql.set_custom_welcome(chat.id, content or text, data_type, buttons)
    msg.reply_text("Successfully set custom welcome message!")

    return (
        "<b>{}:</b>"
        "\n#SET_WELCOME"
        "\n<b>Admin:</b> {}"
        "\nSet the welcome message.".format(
            escape(chat.title), mention_html(user.id, user.first_name)
        )
    )


@user_admin
@loggable
@typing_action
def reset_welcome(update, context) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    sql.set_custom_welcome(chat.id, sql.DEFAULT_WELCOME, sql.Types.TEXT)
    update.effective_message.reply_text(
        "Successfully reset welcome message to default!"
    )
    return (
        "<b>{}:</b>"
        "\n#RESET_WELCOME"
        "\n<b>Admin:</b> {}"
        "\nReset the welcome message to default.".format(
            escape(chat.title), mention_html(user.id, user.first_name)
        )
    )


@user_admin
@loggable
@typing_action
def set_goodbye(update, context) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    msg = update.effective_message  # type: Optional[Message]
    text, data_type, content, buttons = get_welcome_type(msg)

    if data_type is None:
        msg.reply_text("You didn't specify what to reply with!")
        return ""

    sql.set_custom_gdbye(chat.id, content or text, data_type, buttons)
    msg.reply_text("Successfully set custom goodbye message!")
    return (
        "<b>{}:</b>"
        "\n#SET_GOODBYE"
        "\n<b>Admin:</b> {}"
        "\nSet the goodbye message.".format(
            escape(chat.title), mention_html(user.id, user.first_name)
        )
    )


@user_admin
@loggable
@typing_action
def reset_goodbye(update, context) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    sql.set_custom_gdbye(chat.id, sql.DEFAULT_GOODBYE, sql.Types.TEXT)
    update.effective_message.reply_text(
        "Successfully reset goodbye message to default!"
    )
    return (
        "<b>{}:</b>"
        "\n#RESET_GOODBYE"
        "\n<b>Admin:</b> {}"
        "\nReset the goodbye message.".format(
            escape(chat.title), mention_html(user.id, user.first_name)
        )
    )


@user_admin
@loggable
@typing_action
def welcomemute(update, context) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    msg = update.effective_message  # type: Optional[Message]
    args = context.args

    if len(args) >= 1:
        if args[0].lower() in ("off", "no"):
            sql.set_welcome_mutes(chat.id, False)
            msg.reply_text("I will no longer mute people on joining!")
            return (
                "<b>{}:</b>"
                "\n#WELCOME_MUTE"
                "\n<b>• Admin:</b> {}"
                "\nHas toggled welcome mute to <b>OFF</b>.".format(
                    escape(chat.title), mention_html(user.id, user.first_name)
                )
            )
        elif args[0].lower() in ("soft"):
            sql.set_welcome_mutes(chat.id, "soft")
            msg.reply_text(
                "I will restrict user's permission to send media for 24 hours"
            )
            return (
                "<b>{}:</b>"
                "\n#WELCOME_MUTE"
                "\n<b>• Admin:</b> {}"
                "\nHas toggled welcome mute to <b>SOFT</b>.".format(
                    escape(chat.title), mention_html(user.id, user.first_name)
                )
            )
        elif args[0].lower() in ("strong"):
            sql.set_welcome_mutes(chat.id, "strong")
            msg.reply_text(
                "I will now mute people when they join and"
                " click on the button to be unmuted."
            )
            return (
                "<b>{}:</b>"
                "\n#WELCOME_MUTE"
                "\n<b>• Admin:</b> {}"
                "\nHas toggled welcome mute to <b>STRONG</b>.".format(
                    escape(chat.title), mention_html(user.id, user.first_name)
                )
            )
        else:
            msg.reply_text(
                "Please enter `off`/`on`/`soft`/`strong`!",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ""
    else:
        curr_setting = sql.welcome_mutes(chat.id)
        reply = "\n Give me a setting! Choose one of: `off`/`no` or `soft` or `strong` only! \nCurrent setting: `{}`"
        msg.reply_text(
            reply.format(curr_setting), parse_mode=ParseMode.MARKDOWN
        )
        return ""


@user_admin
@loggable
@typing_action
def clean_welcome(update, context) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    args = context.args

    if not args:
        clean_pref = sql.get_clean_pref(chat.id)
        if clean_pref:
            update.effective_message.reply_text(
                "I should be deleting welcome messages up to two days old."
            )
        else:
            update.effective_message.reply_text(
                "I'm currently not deleting old welcome messages!"
            )
        return ""

    if args[0].lower() in ("on", "yes"):
        sql.set_clean_welcome(str(chat.id), True)
        update.effective_message.reply_text(
            "I'll try to delete old welcome messages!"
        )
        return (
            "<b>{}:</b>"
            "\n#CLEAN_WELCOME"
            "\n<b>Admin:</b> {}"
            "\nHas toggled clean welcomes to <code>ON</code>.".format(
                escape(chat.title), mention_html(user.id, user.first_name)
            )
        )
    elif args[0].lower() in ("off", "no"):
        sql.set_clean_welcome(str(chat.id), False)
        update.effective_message.reply_text(
            "I won't delete old welcome messages."
        )
        return (
            "<b>{}:</b>"
            "\n#CLEAN_WELCOME"
            "\n<b>Admin:</b> {}"
            "\nHas toggled clean welcomes to <code>OFF</code>.".format(
                escape(chat.title), mention_html(user.id, user.first_name)
            )
        )
    else:
        # idek what you're writing, say yes or no
        update.effective_message.reply_text(
            "I understand 'on/yes' or 'off/no' only!"
        )
        return ""


@user_admin
@typing_action
def cleanservice(update, context):
    chat = update.effective_chat  # type: Optional[Chat]
    args = context.args
    if chat.type != chat.PRIVATE:
        if len(args) >= 1:
            var = args[0]
            if var == "no" or var == "off":
                sql.set_clean_service(chat.id, False)
                update.effective_message.reply_text(
                    "Turned off service messages cleaning."
                )
            elif var == "yes" or var == "on":
                sql.set_clean_service(chat.id, True)
                update.effective_message.reply_text(
                    "Turned on service messages cleaning!"
                )
            else:
                update.effective_message.reply_text(
                    "Invalid option", parse_mode=ParseMode.MARKDOWN
                )
        else:
            update.effective_message.reply_text(
                "Usage is on/yes or off/no", parse_mode=ParseMode.MARKDOWN
            )
    else:
        curr = sql.clean_service(chat.id)
        if curr:
            update.effective_message.reply_text(
                "Welcome clean service is : on", parse_mode=ParseMode.MARKDOWN
            )
        else:
            update.effective_message.reply_text(
                "Welcome clean service is : off", parse_mode=ParseMode.MARKDOWN
            )


def user_button(update, context):
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    query = update.callback_query  # type: Optional[CallbackQuery]
    match = re.match(r"user_join_\((.+?)\)", query.data)
    message = update.effective_message  # type: Optional[Message]
    db_checks = sql.set_human_checks(user.id, chat.id)
    join_user = int(match.group(1))

    if join_user == user.id:
        query.answer(text="Yus! You're a human, Unmuted!")
        context.bot.restrict_chat_member(
            chat.id,
            user.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_invite_users=True,
                can_pin_messages=True,
                can_send_polls=True,
                can_change_info=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        context.bot.deleteMessage(chat.id, message.message_id)
        db_checks
    else:
        query.answer(text="You're not allowed to do this!")


WELC_HELP_TXT = (
    "Your group's welcome/goodbye messages can be personalised in multiple ways. If you want the messages"
    " to be individually generated, like the default welcome message is, you can use *these* variables:\n"
    " - `{{first}}`: this represents the user's *first* name\n"
    " - `{{last}}`: this represents the user's *last* name. Defaults to *first name* if user has no "
    "last name.\n"
    " - `{{fullname}}`: this represents the user's *full* name. Defaults to *first name* if user has no "
    "last name.\n"
    " - `{{username}}`: this represents the user's *username*. Defaults to a *mention* of the user's "
    "first name if has no username.\n"
    " - `{{mention}}`: this simply *mentions* a user - tagging them with their first name.\n"
    " - `{{id}}`: this represents the user's *id*\n"
    " - `{{count}}`: this represents the user's *member number*.\n"
    " - `{{chatname}}`: this represents the *current chat name*.\n"
    "\nEach variable MUST be surrounded by `{{}}` to be replaced.\n"
    "Welcome messages also support markdown, so you can make any elements bold/italic/code/links. "
    "Buttons are also supported, so you can make your welcomes look awesome with some nice intro "
    "buttons.\n"
    "To create a button linking to your rules, use this: `[Rules](buttonurl://t.me/{}?start=group_id)`. "
    "Simply replace `group_id` with your group's id, which can be obtained via /id, and you're good to "
    "go. Note that group ids are usually preceded by a `-` sign; this is required, so please don't "
    "remove it.\n"
    "If you're feeling fun, you can even set images/gifs/videos/voice messages as the welcome message by "
    "replying to the desired media, and calling /setwelcome.".format(
        dispatcher.bot.username
    )
)


@user_admin
@typing_action
def welcome_help(update, context):
    update.effective_message.reply_text(
        WELC_HELP_TXT, parse_mode=ParseMode.MARKDOWN
    )


# TODO: get welcome data from group butler snap
# def __import_data__(chat_id, data):
#     welcome = data.get('info', {}).get('rules')
#     welcome = welcome.replace('$username', '{username}')
#     welcome = welcome.replace('$name', '{fullname}')
#     welcome = welcome.replace('$id', '{id}')
#     welcome = welcome.replace('$title', '{chatname}')
#     welcome = welcome.replace('$surname', '{lastname}')
#     welcome = welcome.replace('$rules', '{rules}')
#     sql.set_custom_welcome(chat_id, welcome, sql.Types.TEXT)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    welcome_pref, _, _ = sql.get_welc_pref(chat_id)
    goodbye_pref, _, _ = sql.get_gdbye_pref(chat_id)
    clean_welc_pref = sql.get_clean_pref(chat_id)
    welc_mutes_pref = sql.get_welc_mutes_pref(chat_id)
    return (
        "This chat has it's welcome preference set to `{}`.\n"
        "It's goodbye preference is `{}`. \n\n"
        "*Service preferences:*\n"
        "\nClean welcome: `{}`"
        "\nWelcome mutes: `{}`".format(
            welcome_pref, goodbye_pref, clean_welc_pref, welc_mutes_pref
        )
    )


__help__ = """
{}

*Admin only:*
 × /welcome <on/off>: enable/disable Welcome messages.
 × /welcome: Shows current welcome settings.
 × /welcome noformat: Shows current welcome settings, without the formatting - useful to recycle your welcome messages!
 × /goodbye -> Same usage and args as /welcome.
 × /setwelcome <sometext>: Sets a custom welcome message. If used replying to media, uses that media.
 × /setgoodbye <sometext>: Sets a custom goodbye message. If used replying to media, uses that media.
 × /resetwelcome: Resets to the default welcome message.
 × /resetgoodbye: Resets to the default goodbye message.
 × /cleanwelcome <on/off>: On new member, try to delete the previous welcome message to avoid spamming the chat.
 × /cleanservice <on/off>: Clean 'user is joined' service messages automatically.
 × /welcomemute <off/soft/strong>: All users that join, get muted; a button gets added to the welcome message for them to unmute themselves. \
This proves they aren't a bot! soft - restricts users ability to post media for 24 hours. strong - mutes on join until they prove they're not bots.
 × /welcomehelp: View more formatting information for custom welcome/goodbye messages.

Buttons in welcome messages are made easy, everyone hates URLs visible. With button links you can make your chats look more \
tidy and simplified.

An example of using buttons:
You can create a button using `[button text](buttonurl://example.com)`.

If you wish to add more than 1 buttons simply do the following:
`[Button 1](buttonurl://example.com)`
`[Button 2](buttonurl://github.com:same)`
`[Button 3](buttonurl://google.com)`

The `:same` end of the link merges 2 buttons on same line as 1 button, resulting in 3rd button to be separated \
from same line.

Tip: Buttons must be placed at the end of welcome messages.
""".format(
    WELC_HELP_TXT
)

__mod_name__ = "Greetings"

NEW_MEM_HANDLER = MessageHandler(
    Filters.status_update.new_chat_members, new_member
)
LEFT_MEM_HANDLER = MessageHandler(
    Filters.status_update.left_chat_member, left_member
)
WELC_PREF_HANDLER = CommandHandler(
    "welcome", welcome, pass_args=True, filters=Filters.group
)
GOODBYE_PREF_HANDLER = CommandHandler(
    "goodbye", goodbye, pass_args=True, filters=Filters.group
)
SET_WELCOME = CommandHandler("setwelcome", set_welcome, filters=Filters.group)
SET_GOODBYE = CommandHandler("setgoodbye", set_goodbye, filters=Filters.group)
RESET_WELCOME = CommandHandler(
    "resetwelcome", reset_welcome, filters=Filters.group
)
RESET_GOODBYE = CommandHandler(
    "resetgoodbye", reset_goodbye, filters=Filters.group
)
CLEAN_WELCOME = CommandHandler(
    "cleanwelcome", clean_welcome, pass_args=True, filters=Filters.group
)
WELCOMEMUTE_HANDLER = CommandHandler(
    "welcomemute", welcomemute, pass_args=True, filters=Filters.group
)
CLEAN_SERVICE_HANDLER = CommandHandler(
    "cleanservice", cleanservice, pass_args=True, filters=Filters.group
)
WELCOME_HELP = CommandHandler("welcomehelp", welcome_help)
BUTTON_VERIFY_HANDLER = CallbackQueryHandler(
    user_button, pattern=r"user_join_"
)

dispatcher.add_handler(NEW_MEM_HANDLER)
dispatcher.add_handler(LEFT_MEM_HANDLER)
dispatcher.add_handler(WELC_PREF_HANDLER)
dispatcher.add_handler(GOODBYE_PREF_HANDLER)
dispatcher.add_handler(SET_WELCOME)
dispatcher.add_handler(SET_GOODBYE)
dispatcher.add_handler(RESET_WELCOME)
dispatcher.add_handler(RESET_GOODBYE)
dispatcher.add_handler(CLEAN_WELCOME)
dispatcher.add_handler(WELCOMEMUTE_HANDLER)
dispatcher.add_handler(CLEAN_SERVICE_HANDLER)
dispatcher.add_handler(BUTTON_VERIFY_HANDLER)
dispatcher.add_handler(WELCOME_HELP)
