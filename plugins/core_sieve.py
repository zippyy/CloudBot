import asyncio
import logging

from time import time

from cloudbot import hook
from cloudbot.util.tokenbucket import TokenBucket

inited = []

TOKENS = 17.5
RESTORE_RATE = 2.5
MESSAGE_COST = 5

# when STRICT is enabled, every time a user gets ratelimted it wipes
# their tokens so they have to wait at least X seconds to regen
STRICT = True

buckets = {}

logger = logging.getLogger("cloudbot")


def task_clear(loop):
    for uid, _bucket in buckets:
        if (time() - _bucket.timestamp) > 600:
            del buckets[uid]
    loop.call_later(600, task_clear, loop)


@asyncio.coroutine
@hook.irc_raw('004')
def init_tasks(loop, conn):
    if conn.name in inited:
        # tasks already started
        return

    logger.info("[{}|sieve] Bot is starting ratelimiter cleanup task.".format(conn.readable_name))
    loop.call_later(600, task_clear, loop)
    inited.append(conn.name)


@asyncio.coroutine
@hook.sieve
def sieve_suite(bot, event, _hook):
    """
    this function stands between your users and the commands they want to use. it decides if they can or not
    :type bot: cloudbot.bot.CloudBot
    :type event: cloudbot.event.Event
    :type _hook: cloudbot.plugin.Hook
    """
    conn = event.conn
    # check ignore bots
    if event.irc_command == 'PRIVMSG' and event.nick.endswith('bot') and _hook.ignore_bots:
        return None

    # check acls
    acl = conn.config.get('acls', {}).get(_hook.function_name)
    if acl:
        if 'deny-except' in acl:
            allowed_channels = list(map(str.lower, acl['deny-except']))
            if event.chan.lower() not in allowed_channels:
                return None
        if 'allow-except' in acl:
            denied_channels = list(map(str.lower, acl['allow-except']))
            if event.chan.lower() in denied_channels:
                return None

    # check disabled_commands
    if _hook.type == "command":
        disabled_commands = conn.config.get('disabled_commands', [])
        if event.triggered_command in disabled_commands:
            return None

    # check permissions
    allowed_permissions = _hook.permissions
    if allowed_permissions:
        allowed = False
        for perm in allowed_permissions:
            if event.has_permission(perm):
                allowed = True
                break

        if not allowed:
            event.notice("Sorry, you are not allowed to use this command.")
            return None

    # check command spam tokens
    if _hook.type == "command":
        # right now ratelimiting is per-channel, but this can be changed
        uid = (event.chan, event.nick.lower())

        if uid not in buckets:
            bucket = TokenBucket(TOKENS, RESTORE_RATE)
            bucket.consume(MESSAGE_COST)
            buckets[uid] = bucket
            return event

        bucket = buckets[uid]
        if bucket.consume(MESSAGE_COST):
            pass
        else:
            bot.logger.info("[{}|sieve] Refused command from {}. "
                            "Entity had {} tokens, needed {}.".format(conn.readable_name, uid, bucket.tokens,
                                                                      MESSAGE_COST))
            if STRICT:
                # bad person loses all tokens
                bucket.empty()
            return None

    return event


