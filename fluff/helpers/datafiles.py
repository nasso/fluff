import json
import os
import datetime
import math

# Definitions

userlog_event_types = {
    "warns": "Warn",
    "bans": "Ban",
    "kicks": "Kick",
    "tosses": "Toss",
    "notes": "Note",
}

# Bot Files


def make_botfile(filename):
    if not os.path.exists("data"):
        os.makedirs("data")
    with open(f"data/{filename}.json", "w") as f:
        f.write("{}")
        return json.loads("{}")


def get_botfile(filename):
    if not os.path.exists(f"data/{filename}.json"):
        make_botfile(filename)
    with open(f"data/{filename}.json", "r") as f:
        return json.load(f)


def set_botfile(filename, contents):
    with open(f"data/{filename}.json", "w") as f:
        f.write(contents)


# User Files


def make_userfile(userid, filename):
    if not os.path.exists(f"data/users/{userid}"):
        os.makedirs(f"data/users/{userid}")
    with open(f"data/users/{userid}/{filename}.json", "w") as f:
        f.write("{}")
        return json.loads("{}")


def get_userfile(userid, filename):
    if not os.path.exists(f"data/users/{userid}/{filename}.json"):
        make_userfile(userid, filename)
    with open(f"data/users/{userid}/{filename}.json", "r") as f:
        return json.load(f)


def set_userfile(userid, filename, contents):
    with open(f"data/users/{userid}/{filename}.json", "w") as f:
        f.write(contents)


# Guild Files


def make_guildfile(serverid, filename):
    if not os.path.exists(f"data/servers/{serverid}"):
        os.makedirs(f"data/servers/{serverid}")
    with open(f"data/servers/{serverid}/{filename}.json", "w") as f:
        f.write("{}")
        return json.loads("{}")


def get_guildfile(serverid, filename):
    if not os.path.exists(f"data/servers/{serverid}/{filename}.json"):
        make_guildfile(serverid, filename)
    with open(f"data/servers/{serverid}/{filename}.json", "r") as f:
        return json.load(f)


def set_guildfile(serverid, filename, contents):
    with open(f"data/servers/{serverid}/{filename}.json", "w") as f:
        f.write(contents)


# Toss Files


def make_tossfile(serverid, filename):
    if not os.path.exists(f"data/servers/{serverid}/toss"):
        os.makedirs(f"data/servers/{serverid}/toss")
    with open(f"data/servers/{serverid}/toss/{filename}.json", "w") as f:
        f.write("{}")
        return json.loads("{}")


def get_tossfile(serverid, filename):
    if not os.path.exists(f"data/servers/{serverid}/toss/{filename}.json"):
        make_tossfile(serverid, filename)
    with open(f"data/servers/{serverid}/toss/{filename}.json", "r") as f:
        return json.load(f)


def set_tossfile(serverid, filename, contents):
    with open(f"data/servers/{serverid}/toss/{filename}.json", "w") as f:
        f.write(contents)


# Default Fills


def fill_userlog(serverid, userid):
    userlogs = get_guildfile(serverid, "userlog")
    uid = str(userid)
    if uid not in userlogs:
        userlogs[uid] = {
            "warns": [],
            "mutes": [],
            "kicks": [],
            "bans": [],
            "notes": [],
            "watch": {"state": False, "thread": None, "message": None},
        }

    return userlogs, uid


def fill_profile(userid):
    profile = get_userfile(userid, "profile")
    stockprofile = {
        "prefixes": [],
        "aliases": [],
        "timezone": None,
        "replypref": None,
    }
    if not profile:
        profile = stockprofile

    # Validation
    updated = False
    for key, value in stockprofile.items():
        if key not in profile:
            profile[key] = value
            updated = True
    for key, value in profile.items():
        if key not in stockprofile:
            del profile[key]
            updated = True

    if updated:
        set_userfile(userid, "profile", json.dumps(profile))

    return profile


# Userlog Features


def add_userlog(sid, uid, issuer, reason, event_type):
    userlogs, uid = fill_userlog(sid, uid)

    log_data = {
        "issuer_id": issuer.id,
        "reason": reason,
        "timestamp": int(datetime.datetime.now().timestamp()),
    }
    if event_type not in userlogs[uid]:
        userlogs[uid][event_type] = []
    userlogs[uid][event_type].append(log_data)
    set_guildfile(sid, "userlog", json.dumps(userlogs))
    return len(userlogs[uid][event_type])


def toss_userlog(sid, uid, issuer, mlink, cid):
    userlogs, uid = fill_userlog(sid, uid)

    toss_data = {
        "issuer_id": issuer.id,
        "session_id": cid,
        "post_link": mlink,
        "timestamp": int(datetime.datetime.now().timestamp()),
    }
    if "tosses" not in userlogs[uid]:
        userlogs[uid]["tosses"] = []
    userlogs[uid]["tosses"].append(toss_data)
    set_guildfile(sid, "userlog", json.dumps(userlogs))
    return len(userlogs[uid]["tosses"])

def rulepush_userlog(guild_id: int, user_id: int, issuer_id: int, msg_url: str, channel_id: int):
    userlogs, user_id_str = fill_userlog(guild_id, user_id)

    rulepush_data = {
        "issuer_id": issuer_id,
        "session_id": channel_id,
        "post_link": msg_url,
        "timestamp": int(datetime.datetime.now().timestamp()),
    }
    if "rulepushes" not in userlogs[user_id_str]:
        userlogs[user_id_str]["rulepushes"] = []
    userlogs[user_id_str]["rulepushes"].append(rulepush_data)
    set_guildfile(guild_id, "userlog", json.dumps(userlogs))
    return len(userlogs[user_id_str]["rulepushes"])

def watch_userlog(sid, uid, issuer, watch_state, tracker_thread=None, tracker_msg=None):
    userlogs, uid = fill_userlog(sid, uid)

    userlogs[uid]["watch"] = {
        "state": watch_state,
        "thread": tracker_thread,
        "message": tracker_msg,
    }
    set_guildfile(sid, "userlog", json.dumps(userlogs))
    return


# Dishtimer Features


def add_job(job_type, job_name, job_details, timestamp):
    timestamp = str(math.floor(timestamp))
    job_name = str(job_name)
    ctab = get_botfile("timers")

    if job_type not in ctab:
        ctab[job_type] = {}

    if timestamp not in ctab[job_type]:
        ctab[job_type][timestamp] = {}

    ctab[job_type][timestamp][job_name] = job_details
    set_botfile("timers", json.dumps(ctab))


def delete_job(timestamp, job_type, job_name):
    timestamp = str(timestamp)
    job_name = str(job_name)
    ctab = get_botfile("timers")

    del ctab[job_type][timestamp][job_name]

    # smh, not checking for empty timestamps. Smells like bloat!
    if not ctab[job_type][timestamp]:
        del ctab[job_type][timestamp]

    set_botfile("timers", json.dumps(ctab))
