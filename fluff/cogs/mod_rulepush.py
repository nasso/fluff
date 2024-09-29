import random
import re
import asyncio
import os
import zipfile
import discord
import json

from itertools import zip_longest
from typing import Union
from discord.ext import commands
from discord.ext.commands import Cog

from helpers.archive import log_channel
from helpers.google import upload
from helpers.embeds import author_embed, createdat_embed, joinedat_embed, mod_embed, stock_embed
from helpers.placeholders import random_msg
from helpers.checks import ismod
from helpers.sv_config import get_config
from helpers.datafiles import get_tossfile, rulepush_userlog, set_tossfile

class RulePush(Cog):

    def __init__(self, bot):
        self.bot = bot
        self.poketimers = dict()
        self.nocfgmsg = "Rule-pushing isn't enabled for this server."
        self.guild_rulepushes: dict[int, set[int]] = dict()

    def enabled(self, g):
        return all(
            (
                self.bot.pull_role(g, get_config(g.id, "rulepush", "rulepushrole")),
                self.bot.pull_category(
                    g, get_config(g.id, "rulepush", "rulepushcategory")
                ),
                get_config(g.id, "rulepush", "rulepushchannels"),
            )
        )

    def username_system(self, user):
        return (
            "**"
            + self.bot.pacify_name(user.global_name)
            + f"** [{self.bot.pacify_name(str(user))}]"
            if user.global_name
            else f"**{self.bot.pacify_name(str(user))}**"
        )

    @commands.bot_has_permissions(
        manage_roles=True, manage_channels=True, add_reactions=True
    )
    @commands.check(ismod)
    @commands.guild_only()
    @commands.group(aliases=["rp"], invoke_without_command=True)
    async def rulepush(self, ctx: commands.Context, users: commands.Greedy[discord.Member]):
        """This rulepushes a user.

        Please refer to no section of any documentation. Good luck, have fun.

        - `users`
        The users to rulepush."""
        assert ctx.guild != None
        assert not isinstance(ctx.channel, discord.DMChannel)
        assert not isinstance(ctx.channel, discord.Thread)
        assert not isinstance(ctx.channel, discord.PartialMessageable)
        assert not isinstance(ctx.channel, discord.GroupChannel)

        if not self.enabled(ctx.guild):
            return await ctx.reply(self.nocfgmsg, mention_author=False)

        staff_roles = [
            self.bot.pull_role(ctx.guild, get_config(ctx.guild.id, "staff", "modrole")),
            self.bot.pull_role(
                ctx.guild, get_config(ctx.guild.id, "staff", "adminrole")
            ),
        ]
        rulepush_role = self.bot.pull_role(
            ctx.guild, get_config(ctx.guild.id, "rulepush", "rulepushrole")
        )
        if not any(staff_roles) or not rulepush_role:
            return await ctx.reply(
                content="PLACEHOLDER no staff or rulepush role configured",
                mention_author=False,
            )
        notify_channel = self.bot.pull_channel(
            ctx.guild, get_config(ctx.guild.id, "rulepush", "notificationchannel")
        )
        if not notify_channel:
            notify_channel = self.bot.pull_channel(
                ctx.guild, get_config(ctx.guild.id, "staff", "staffchannel")
            )
        modlog_channel = self.bot.pull_channel(
            ctx.guild, get_config(ctx.guild.id, "logging", "modlog")
        )

        errors = ""
        for us in users:
            if us.id == ctx.author.id:
                errors += f"\n- {self.username_system(us)}\n  You cannot rulepush yourself."
            elif us.id == self.bot.application_id:
                errors += f"\n- {self.username_system(us)}\n  You cannot rulepush the bot."
            elif self.get_session(us) and rulepush_role in us.roles:
                errors += (
                    f"\n- {self.username_system(us)}\n  This user is already rulepushed."
                )
            else:
                continue
            users.remove(us)
        if not users:
            await ctx.message.add_reaction("🚫")
            return await notify_channel.send(
                f"Error in rulepush command from {ctx.author.mention}...\n- Nobody was rulepushed.\n```diff"
                + errors
                + "\n```\n"
            )

        if ctx.channel.name in get_config(ctx.guild.id, "rulepush", "rulepushchannels"):
            addition = True
            rulepush_channel = ctx.channel
        else:
            addition = False
            rulepush_channel = await self.new_session(ctx.guild)
            if not rulepush_channel:
                await ctx.message.add_reaction("🚫")
                return await notify_channel.send(
                    f"Error in rulepush command from {ctx.author.mention}...\n- No rulepush channels available.\n```diff"
                    + errors
                    + "\n```\n"
                )

        for us in users:
            try:
                failed_roles, previous_roles = await self.perform_rulepush(
                    us, ctx.author, rulepush_channel.name
                )
                # it should be safe to assert here because we already check if
                # the user is already role banned above
                assert failed_roles != None
                assert previous_roles != None
                await rulepush_channel.set_permissions(us, read_messages=True)
            except commands.MissingPermissions:
                errors += f"\n- {self.username_system(us)}\n  Missing permissions to rulepush this user."
                continue

            rulepush_userlog(
                ctx.guild.id,
                us.id,
                ctx.author.id,
                ctx.message.jump_url,
                rulepush_channel.id,
            )

            if notify_channel:
                embed = stock_embed(self.bot)
                author_embed(embed, us, True)
                embed.color = ctx.author.color
                embed.title = "🚷 Rulepush"
                embed.description = f"{us.mention} was rulepushed by {ctx.author.mention} [`#{ctx.channel.name}`] [[Jump]({ctx.message.jump_url})]\n> This rulepush takes place in {rulepush_channel.mention}..."
                createdat_embed(embed, us)
                joinedat_embed(embed, us)
                prevlist = []
                if len(previous_roles) > 0:
                    for role in previous_roles:
                        prevlist.append("<@&" + str(role.id) + ">")
                    prevlist = ",".join(reversed(prevlist))
                else:
                    prevlist = "None"
                embed.add_field(
                    name="🎨 Previous Roles",
                    value=prevlist,
                    inline=False,
                )
                if failed_roles:
                    faillist = []
                    for role in failed_roles:
                        faillist.append("<@&" + str(role.id) + ">")
                    faillist = ",".join(reversed(faillist))
                    embed.add_field(
                        name="🚫 Failed Roles",
                        value=faillist,
                        inline=False,
                    )
                await notify_channel.send(embed=embed)

            if modlog_channel and modlog_channel != notify_channel:
                embed = stock_embed(self.bot)
                embed.color = discord.Color.from_str("#FF0000")
                embed.title = "🚷 Rulepush"
                embed.description = f"{us.mention} was rulepushed by {ctx.author.mention} [`#{ctx.channel.name}`] [[Jump]({ctx.message.jump_url})]"
                mod_embed(embed, us, ctx.author)
                await modlog_channel.send(embed=embed)

        await ctx.message.add_reaction("🚷")

        if errors and notify_channel:
            return await notify_channel.send(
                f"Error in rulepush command from {ctx.author.mention}...\n- Some users could not be rulepushed.\n```diff"
                + errors
                + "\n```\n"
            )

        if not addition:
            rulepush_pings = ", ".join([us.mention for us in users])
            await rulepush_channel.send(
                f"{rulepush_pings}\nYou were rulepushed by {self.bot.pacify_name(ctx.author.display_name)}.\n{get_config(ctx.guild.id, 'rulepush', 'rulepushmsg')}"
            )

            def check(m):
                return m.author in users and m.channel == rulepush_channel

            try:
                self.poketimers[str(rulepush_channel.id)] = self.bot.wait_for(
                    "message", timeout=300, check=check
                )
            except asyncio.TimeoutError:
                pokemsg = await rulepush_channel.send(ctx.author.mention)
                await pokemsg.edit(content="⏰", delete_after=5)
            else:
                try:
                    pokemsg = await rulepush_channel.send(ctx.author.mention)
                    await pokemsg.edit(content="🫳⏰", delete_after=5)
                except discord.errors.NotFound:
                    return

    @commands.cooldown(1, 5, commands.BucketType.guild)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    @commands.check(ismod)
    @commands.guild_only()
    @commands.command(aliases=["unrp", "rulepop"])
    async def rulepull(
        self,
        ctx: commands.Context,
        users: Union[commands.Greedy[discord.Member], None] = None
    ):
        """This rulepulls a user (undo the rulepush).

        Please refer to no section of any documentation. Good luck, have fun.

        - `users`
        The users to rulepull. Optional."""
        assert ctx.guild != None
        assert not isinstance(ctx.channel, discord.DMChannel)
        assert not isinstance(ctx.channel, discord.Thread)
        assert not isinstance(ctx.channel, discord.PartialMessageable)
        assert not isinstance(ctx.channel, discord.GroupChannel)

        if not self.enabled(ctx.guild):
            return await ctx.reply(self.nocfgmsg, mention_author=False)

        rulepush_channels = get_config(ctx.guild.id, "rulepush", "rulepushchannels")
        if ctx.channel.name not in rulepush_channels:
            return await ctx.reply(
                content="This command must be run inside of a rulepush channel.",
                mention_author=False,
            )

        rulepushes = get_tossfile(ctx.guild.id, "rulepushes")

        if not rulepushes:
            return await ctx.reply(self.nocfgmsg, mention_author=False)

        user_list = [
            u
            for u in [
                ctx.guild.get_member(int(u))
                for u in rulepushes[ctx.channel.name]["rulepushed"].keys()
            ]
            if u
        ] if not users else [u for u in users]

        notify_channel = self.bot.pull_channel(
            ctx.guild, get_config(ctx.guild.id, "rulepush", "notificationchannel")
        )
        if not notify_channel:
            notify_channel = self.bot.pull_channel(
                ctx.guild, get_config(ctx.guild.id, "staff", "staffchannel")
            )
        rulepush_role = self.bot.pull_role(
            ctx.guild, get_config(ctx.guild.id, "rulepush", "rulepushrole")
        )
        output = ""
        invalid = []

        for us in user_list:
            if us.id == self.bot.application_id:
                output += "\n" + random_msg(
                    "warn_targetbot", authorname=ctx.author.name
                )
            elif us.id == ctx.author.id:
                output += "\n" + random_msg(
                    "warn_targetself", authorname=ctx.author.name
                )
            elif (
                str(us.id) not in rulepushes[ctx.channel.name]["rulepushed"]
                and rulepush_role not in us.roles
            ):
                output += "\n" + f"{self.username_system(us)} is not already rulepushed."
            else:
                continue
            user_list.remove(us)
        if not user_list:
            return await ctx.reply(
                output
                + "\n\n"
                + "There's nobody left to rulepull, so nobody was rulepulled.",
                mention_author=False,
            )

        for us in user_list:
            roles = rulepushes[ctx.channel.name]["rulepushed"][str(us.id)]
            if us.id not in rulepushes[ctx.channel.name]["rulepulled"]:
                rulepushes[ctx.channel.name]["rulepulled"].append(us.id)
            del rulepushes[ctx.channel.name]["rulepushed"][str(us.id)]
            self.guild_rulepushes[ctx.guild.id].discard(us.id)

            if roles:
                roles = [r for r in [ctx.guild.get_role(r) for r in roles] if r]
                for r in roles:
                    if not r or not r.is_assignable():
                        roles.remove(r)
                await us.add_roles(
                    *roles,
                    reason=f"Rulepulled by {ctx.author} ({ctx.author.id})",
                    atomic=False,
                )
            await us.remove_roles(
                rulepush_role,
                reason=f"Rulepulled by {ctx.author} ({ctx.author.id})",
            )

            await ctx.channel.set_permissions(us, overwrite=None)

            output += "\n" + f"{self.username_system(us)} has been rulepulled."
            if notify_channel:
                embed = stock_embed(self.bot)
                author_embed(embed, us)
                embed.color = ctx.author.color
                embed.title = "🚶 Rulepull"
                embed.description = f"{us.mention} was rulepulled by {ctx.author.mention} [`#{ctx.channel.name}`]"
                createdat_embed(embed, us)
                joinedat_embed(embed, us)
                prevlist = []
                if len(roles) > 0:
                    for role in roles:
                        prevlist.append("<@&" + str(role.id) + ">")
                    prevlist = ",".join(reversed(prevlist))
                else:
                    prevlist = "None"
                embed.add_field(
                    name="🎨 Restored Roles",
                    value=prevlist,
                    inline=False,
                )
                await notify_channel.send(embed=embed)

        set_tossfile(ctx.guild.id, "rulepushes", json.dumps(rulepushes))

        if invalid:
            output += (
                "\n\n"
                + "I was unable to rulepull these users: "
                + ", ".join([str(iv) for iv in invalid])
            )

        if not rulepushes[ctx.channel.name]:
            output += "\n\n" + "There is nobody left in this session."

        await ctx.reply(content=output, mention_author=False)

    @commands.bot_has_permissions(embed_links=True)
    @commands.check(ismod)
    @commands.guild_only()
    @commands.command(name="rp-sessions", aliases=["rulepushed", "rp-session"])
    async def sessions(self, ctx: commands.Context):
        """This shows the open rulepush sessions.

        Use this in a rulepush channel to show who's in it.

        No arguments."""
        assert ctx.guild != None
        assert not isinstance(ctx.channel, discord.DMChannel)
        assert not isinstance(ctx.channel, discord.Thread)
        assert not isinstance(ctx.channel, discord.PartialMessageable)
        assert not isinstance(ctx.channel, discord.GroupChannel)

        if not self.enabled(ctx.guild):
            return await ctx.reply(self.nocfgmsg, mention_author=False)
        embed = stock_embed(self.bot)
        embed.title = "👁‍🗨 Rulepush Channel Sessions..."
        embed.color = ctx.author.color
        rulepushes = get_tossfile(ctx.guild.id, "rulepushes")

        channels = get_config(ctx.guild.id, "rulepush", "rulepushchannels")

        if ctx.channel.name in channels:
            channels = [ctx.channel.name]

        for c in channels:
            if c in [g.name for g in ctx.guild.channels]:
                if c not in rulepushes or not rulepushes[c]["rulepushed"]:
                    embed.add_field(
                        name=f"🟡 #{c}",
                        value="__Empty__\n> Please close the channel.",
                        inline=True,
                    )
                else:
                    userlist = "\n".join(
                        [
                            f"> {self.username_system(user)}"
                            for user in [
                                await self.bot.fetch_user(str(u))
                                for u in rulepushes[c]["rulepushed"].keys()
                            ]
                        ]
                    )
                    embed.add_field(
                        name=f"🔴 #{c}",
                        value=f"__Occupied__\n{userlist}",
                        inline=True,
                    )
            else:
                embed.add_field(name=f"🟢 #{c}", value="__Available__", inline=True)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.bot_has_permissions(embed_links=True, add_reactions=True)
    @commands.check(ismod)
    @commands.guild_only()
    @commands.command(name="rp-close")
    async def close(self, ctx: commands.Context, archive=True):
        """This closes a rulepush session.

        Please refer to the tossing section of the [documentation](https://3gou.0ccu.lt/as-a-moderator/the-tossing-system/).
        In Fluff, this command also sends archival data to Google Drive.

        - No arguments.
        """
        assert ctx.guild != None
        assert not isinstance(ctx.channel, discord.DMChannel)
        assert not isinstance(ctx.channel, discord.Thread)
        assert not isinstance(ctx.channel, discord.PartialMessageable)
        assert not isinstance(ctx.channel, discord.GroupChannel)

        if not self.enabled(ctx.guild):
            return await ctx.reply(self.nocfgmsg, mention_author=False)
        if ctx.channel.name not in get_config(ctx.guild.id, "rulepush", "rulepushchannels"):
            return await ctx.reply(
                content="This command must be run inside of a rulepush channel.",
                mention_author=False,
            )

        notify_channel = self.bot.pull_channel(
            ctx.guild, get_config(ctx.guild.id, "rulepush", "notificationchannel")
        )
        if not notify_channel:
            notify_channel = self.bot.pull_channel(
                ctx.guild, get_config(ctx.guild.id, "staff", "staffchannel")
            )
        logging_channel = self.bot.pull_channel(
            ctx.guild, get_config(ctx.guild.id, "logging", "modlog")
        )
        rulepushes = get_tossfile(ctx.guild.id, "rulepushes")

        try:
            if rulepushes[ctx.channel.name]["rulepushed"]:
                return await ctx.reply(
                    content="You must rulepull everyone first!", mention_author=True
                )
        except KeyError:
            # This might be a bad idea.
            return await ctx.channel.delete(
                reason="Fluff Rulepush (No one was rulepushed, KeyError except)"
            )

        embed = stock_embed(self.bot)
        embed.title = "Rulepush Session Closed (Fluff)"
        embed.description = f"`#{ctx.channel.name}`'s session was closed by {ctx.author.mention} ({ctx.author.id})."
        embed.color = ctx.author.color
        embed.set_author(name=ctx.author, icon_url=ctx.author.display_avatar.url)

        if archive:
            async with ctx.channel.typing():
                dotraw, dotzip = await log_channel(
                    self.bot, ctx.channel, zip_files=True
                )

            users = []
            for uid in (
                rulepushes[ctx.channel.name]["rulepulled"] + rulepushes[ctx.channel.name]["left"]
            ):
                if self.bot.get_user(uid):
                    users.append(self.bot.get_user(uid))
                else:
                    user = await self.bot.fetch_user(uid)
                    users.append(user)
            user = f""

            if users:
                firstuser = f"{users[0].name} {users[0].id}"
            else:
                firstuser = f"unspecified (logged by {ctx.author.name})"

            filename = (
                ctx.message.created_at.astimezone().strftime("%Y-%m-%d")
                + f" {firstuser}"
            )
            reply = (
                f"📕 I've archived that as: `{filename}.txt`\nThis rulepush session had the following users:\n- "
                + "\n- ".join([f"{self.username_system(u)} ({u.id})" for u in users])
            )
            dotraw += f"\n{ctx.message.created_at.astimezone().strftime('%Y/%m/%d %H:%M')} {self.bot.user} [BOT]\n{reply}"

            if not os.path.exists(
                f"data/servers/{ctx.guild.id}/toss/archives/sessions/{ctx.channel.id}"
            ):
                os.makedirs(
                    f"data/servers/{ctx.guild.id}/toss/archives/sessions/{ctx.channel.id}"
                )
            with open(
                f"data/servers/{ctx.guild.id}/toss/archives/sessions/{ctx.channel.id}/{filename}.txt",
                "w",
                encoding="UTF-8",
            ) as filetxt:
                filetxt.write(dotraw)
            if dotzip:
                with open(
                    f"data/servers/{ctx.guild.id}/toss/archives/sessions/{ctx.channel.id}/{filename} (files).zip",
                    "wb",
                ) as filezip:
                    filezip.write(dotzip.getbuffer())

            embed.add_field(
                name="🗒️ Text",
                value=f"{filename}.txt\n"
                + f"`"
                + str(len(dotraw.split("\n")))
                + "` lines, "
                + f"`{len(dotraw.split())}` words, "
                + f"`{len(dotraw)}` characters.",
                inline=True,
            )
            if dotzip:
                embed.add_field(
                    name="📁 Files",
                    value=f"{filename} (files).zip"
                    + "\n"
                    + f"`{len(zipfile.ZipFile(dotzip, 'r', zipfile.ZIP_DEFLATED).namelist())}` files in the zip file.",
                    inline=True,
                )

            await upload(
                ctx,
                filename,
                f"data/servers/{ctx.guild.id}/toss/archives/sessions/{ctx.channel.id}/",
                dotzip,
            )

        del rulepushes[ctx.channel.name]
        set_tossfile(ctx.guild.id, "rulepushes", json.dumps(rulepushes))

        channel = notify_channel if notify_channel else logging_channel
        if channel:
            await channel.send(embed=embed)
            await ctx.channel.delete(reason="Fluff Rulepush")

    @commands.bot_has_permissions(embed_links=True, add_reactions=True)
    @commands.check(ismod)
    @commands.guild_only()
    @commands.command(name="rewrite-rules")
    async def rewrite_rules(self, ctx: commands.Context, force=True):
        """This rewrites the rules channel.

        - No arguments.
        """
        assert ctx.guild != None
        assert not isinstance(ctx.channel, discord.DMChannel)
        assert not isinstance(ctx.channel, discord.Thread)
        assert not isinstance(ctx.channel, discord.PartialMessageable)
        assert not isinstance(ctx.channel, discord.GroupChannel)

        config_dir = f"data/servers/{ctx.guild.id}/rule-channels"

        notify_channel = self.bot.pull_channel(
            ctx.guild, get_config(ctx.guild.id, "staff", "staffchannel")
        )
        codewords_min = int(get_config(ctx.guild.id, "rulepush", "codewords_min"))
        codewords_max = int(get_config(ctx.guild.id, "rulepush", "codewords_max"))
        all_codewords = [str(w) for w in get_config(ctx.guild.id, "rulepush", "codewords")]

        if not os.path.isdir(config_dir):
            if force:
                await ctx.message.add_reaction("🚫")
                await ctx.reply("No `rule-channels/` directory", mention_author=False)
            else:
                await notify_channel.send(
                    f"Rules not updated: `{config_dir}` does not exist or isn't a directory"
                )
            return

        config_files = [
            f
            for f in os.listdir(config_dir)
            if os.path.isfile(os.path.join(config_dir, f))
        ]

        await ctx.message.add_reaction("⏳")

        used_codewords: dict[int, list[str]] = {}

        pat = re.compile(r"^(\d+)\.md$")
        between_sentences_pat = re.compile(r"[\.!\?] +\w")
        between_words_pat = re.compile(r"\w +\w")
        for fname in config_files:
            m = pat.search(fname)
            if not m:
                continue
            rules_chan_id = int(m.group(1))
            rules_chan = self.bot.pull_channel(ctx.guild, rules_chan_id)
            assert isinstance(rules_chan, discord.TextChannel)

            used_codewords[rules_chan_id] = []

            codewords = random.sample(
                all_codewords,
                random.randrange(codewords_min, codewords_max + 1)
            )

            # read the complete rules from the file (split by line)
            with open(os.path.join(config_dir, fname)) as f:
                rule_lines = f.readlines()

            # pick the lines that will get a codeword (only lines > 70 chars)
            codewords_line_numbers = random.sample(
                [i for i, l in enumerate(rule_lines) if len(l) > 70],
                len(codewords)
            )
            for codeword, idx in zip(codewords, codewords_line_numbers):
                line = rule_lines[idx]
                insert_pat = random.choices(
                    population=[between_sentences_pat, between_words_pat],
                    weights=[0.9, 0.1],
                    k=1
                )[0]
                candidates = list(insert_pat.finditer(line))
                if len(candidates) == 0:
                    insert_pat = between_words_pat
                    candidates = list(insert_pat.finditer(line))
                if len(candidates) == 0:
                    # rip, we can't insert it here
                    continue

                candidate = random.choice(candidates)
                rule_lines[idx] = line[:candidate.start() + 1]
                if insert_pat == between_sentences_pat:
                    rule_lines[idx] += f" {codeword.title()}. "
                else:
                    rule_lines[idx] += f" – {codeword} – "
                rule_lines[idx] += line[candidate.end() - 1:]
                used_codewords[rules_chan_id].append(codeword)

            # combine lines we want to keep in the same message
            rule_parts: list[str] = []
            for line in rule_lines:
                prev = rule_parts[-1] if len(rule_parts) > 0 else None

                if prev != None:
                    if prev.startswith("> ") and line.startswith("> "):
                        rule_parts[-1] += line
                        continue

                rule_parts.append(line)

            # break it down so that it fits into individual messages
            rules_messages = [""]
            for part in rule_parts:
                if len(rules_messages[-1]) + len(part) > 1800:
                    rules_messages.append(part)
                else:
                    rules_messages[-1] += part

            # find existing messages
            existing_messages = [
                msg
                async for msg in rules_chan.history(oldest_first=True)
                if msg.author.id == self.bot.application_id
            ]

            # update the messages
            for (new_msg, cur_msg) in zip_longest(rules_messages,
                                                  existing_messages,
                                                  fillvalue=None):
                if cur_msg == None:
                    # we ran out of existing messages to edit: send a new one!
                    await rules_chan.send(new_msg)
                elif new_msg == None:
                    # no more messages! delete all other pre-existing messages
                    await cur_msg.delete()
                else:
                    # existing message available, edit it!
                    await cur_msg.edit(content=new_msg)

        set_tossfile(ctx.guild.id, "rule-codewords", json.dumps(used_codewords))

        await ctx.message.remove_reaction("⏳", self.bot.user)
        await ctx.message.add_reaction("✅")

    @Cog.listener()
    async def on_message(self, msg: discord.Message):
        await self.bot.wait_until_ready()

        # let's try to eliminate all messages we don't care about
        # we must avoid doing any costly operation (e.g. loading a file)
        # remember this function will get called on *every* message!!

        if msg.guild == None:
            return

        if not isinstance(msg.channel, discord.TextChannel):
            return

        # loads the list of rulepushed users if necessary
        if msg.guild.id not in self.guild_rulepushes:
            uids: set[int] = set()
            rulepushes = get_tossfile(msg.guild.id, "rulepushes")
            if rulepushes:
                for chan in rulepushes.values():
                    for uid in chan["rulepushed"]:
                        uids.add(int(uid))
            self.guild_rulepushes[msg.guild.id] = uids

        if msg.author.id not in self.guild_rulepushes[msg.guild.id]:
            return

        # ok if we're here this is a message we care about!
        # we can safely do more costly things now
        notify_channel: discord.TextChannel = self.bot.pull_channel(
            msg.guild,
            get_config(msg.guild.id, "rulepush", "notificationchannel")
        )

        rulepushes = get_tossfile(msg.guild.id, "rulepushes")
        real_codewords: dict[str, list[str]] = get_tossfile(msg.guild.id, "rule-codewords")

        if (
            not rulepushes or
            not real_codewords or
            msg.channel.name not in rulepushes or
            str(msg.author.id) not in rulepushes[msg.channel.name]["rulepushed"]
        ):
            # shouldn't happen but maybe `guild_rulepushes` was wrong?
            if notify_channel:
                await notify_channel.send(
                    f"I feel like I should pay attention to [this message](<{msg.jump_url}>) but I am not 100% sure. I may have lost track of who is rulepushed, a restart could help!"
                )
            return

        expected_codewords = set(
            cw.lower()
            for cws in real_codewords.values()
            for cw in cws
        )
        submissions: set[str] = (
            set(rulepushes[msg.channel.name].get("submissions", set()))
        )

        word = msg.clean_content.strip().lower()

        if word == "done":
            if submissions >= expected_codewords:
                await msg.reply(get_config(msg.guild.id, "rulepush", "codewords_done"))
                await asyncio.sleep(int(get_config(msg.guild.id, "rulepush", "codewords_done_timeout_secs")))
                await msg.reply("(uhm actually idk how to yet)")
            else:
                await msg.reply(get_config(msg.guild.id, "rulepush", "codewords_not_done"))
        else:
            submissions.add(word)
            rulepushes[msg.channel.name]["submissions"] = list(submissions)
            set_tossfile(msg.guild.id, "rulepushes", json.dumps(rulepushes))

            if word in expected_codewords: 
                await msg.reply(get_config(msg.guild.id, "rulepush", "codeword_ok"))
            else:
                await msg.reply(get_config(msg.guild.id, "rulepush", "codeword_ko"))

    def get_session(self, member: discord.Member):
        rulepushes = get_tossfile(member.guild.id, "rulepushes")
        if not rulepushes:
            return None
        session = None
        if "LEFTGUILD" in rulepushes and str(member.id) in rulepushes["LEFTGUILD"]:
            session = False
        for channel in rulepushes:
            if channel == "LEFTGUILD":
                continue
            if str(member.id) in rulepushes[channel]["rulepushed"]:
                session = channel
                break
        return session

    async def new_session(self, guild: discord.Guild):
        staff_roles = [
            self.bot.pull_role(guild, get_config(guild.id, "staff", "modrole")),
            self.bot.pull_role(guild, get_config(guild.id, "staff", "adminrole")),
        ]
        bot_role = self.bot.pull_role(guild, get_config(guild.id, "staff", "botrole"))
        rulepushes = get_tossfile(guild.id, "rulepushes")

        for c in get_config(guild.id, "rulepush", "rulepushchannels"):
            if c not in [g.name for g in guild.channels]:
                if c not in rulepushes:
                    rulepushes[c] = {"rulepushed": {}, "rulepulled": [], "left": []}
                    set_tossfile(guild.id, "rulepushes", json.dumps(rulepushes))

                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        read_messages=False
                    ),
                    guild.me: discord.PermissionOverwrite(read_messages=True),
                }
                if bot_role:
                    overwrites[bot_role] = discord.PermissionOverwrite(
                        read_messages=True
                    )
                for staff_role in staff_roles:
                    if not staff_role:
                        continue
                    overwrites[staff_role] = discord.PermissionOverwrite(
                        read_messages=True
                    )
                rulepush_channel = await guild.create_text_channel(
                    c,
                    reason="Fluff Rulepush",
                    category=self.bot.pull_category(
                        guild, get_config(guild.id, "rulepush", "rulepushcategory")
                    ),
                    overwrites=overwrites,
                    topic=get_config(guild.id, "rulepush", "rulepushtopic"),
                )

                return rulepush_channel

    async def perform_rulepush(
        self,
        user: discord.Member,
        staff: discord.abc.User,
        rulepush_channel_name: str,
    ):
        rulepush_role = self.bot.pull_role(
            user.guild, get_config(user.guild.id, "rulepush", "rulepushrole")
        )

        if rulepush_role in user.roles:
            return None, None

        roles = [
            rx
            for rx in user.roles
            if rx != user.guild.default_role and rx != rulepush_role
        ]

        rulepushes = get_tossfile(user.guild.id, "rulepushes")
        rulepushes[rulepush_channel_name]["rulepushed"][str(user.id)] = [role.id for role in roles]
        self.guild_rulepushes[user.guild.id].add(user.id)
        set_tossfile(user.guild.id, "rulepushes", json.dumps(rulepushes))

        await user.add_roles(rulepush_role, reason="User rulepushed.")
        fail_roles = []
        if roles:
            for rr in roles:
                if not rr.is_assignable():
                    fail_roles.append(rr)
                    roles.remove(rr)
            await user.remove_roles(
                *roles,
                reason=f"User rulepushed by {staff} ({staff.id})",
                atomic=False,
            )

        return fail_roles, roles


async def setup(bot):
    await bot.add_cog(RulePush(bot))
