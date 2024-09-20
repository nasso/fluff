import asyncio
import os
import zipfile
import discord
import json

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
    async def close(self, ctx, archive=True):
        """This closes a rulepush session.

        Please refer to the tossing section of the [documentation](https://3gou.0ccu.lt/as-a-moderator/the-tossing-system/).
        In Fluff, this command also sends archival data to Google Drive.

        - No arguments.
        """
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
        set_tossfile(ctx.guild.id, "tosses", json.dumps(rulepushes))

        channel = notify_channel if notify_channel else logging_channel
        if channel:
            await channel.send(embed=embed)
            await ctx.channel.delete(reason="Fluff Rulepush")

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
