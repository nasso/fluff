import asyncio
import discord
from discord.ext import commands
from discord.ext.commands import Cog
import config
from helpers.checks import check_if_staff


class ModReact(Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.guild_only()
    @commands.check(check_if_staff)
    @commands.command(aliases=["uclearreacts", "uclrr"])
    async def clearreactsbyuser(
        self,
        ctx,
        user: discord.Member,
        *,
        channel: discord.TextChannel = None,
        limit: int = 50,
    ):
        """[S] Clears reactions from a user."""
        log_channel = self.bot.get_channel(config.modlog_channel)
        if not channel:
            channel = ctx.channel
        count = 0
        async for msg in channel.history(limit=limit):
            for react in msg.reactions:
                if await react.users().find(lambda u: u == user):
                    count += 1
                    async for u in react.users():
                        await msg.remove_reaction(react, u)
        msg = (
            f"✏️ **Cleared reacts**: {ctx.author.name} cleared "
            f"{user}'s reacts from the last {limit} messages "
            f"in {channel.mention}."
        )
        await ctx.channel.send(f"🚮 `{limit}` reactions cleared.", delete_after=5)
        await log_channel.send(msg)

    @commands.guild_only()
    @commands.check(check_if_staff)
    @commands.command(aliases=["purgereacts", "clearreacts", "clrr"])
    async def clearallreacts(
        self, ctx, *, channel: discord.TextChannel = None, limit: int = 50
    ):
        """[S] Clears all reactions in a channel."""
        log_channel = self.bot.get_channel(config.modlog_channel)
        if not channel:
            channel = ctx.channel
        count = 0
        async for msg in channel.history(limit=limit):
            if msg.reactions:
                count += 1
                await msg.clear_reactions()
        msg = (
            f"✏️ **Cleared reacts**: {ctx.author.name} cleared all "
            f"reacts from the last {limit} messages in {channel.mention}."
        )
        await ctx.channel.send(f"🚮 `{count}` reactions purged.", delete_after=5)
        await log_channel.send(msg)

    @commands.guild_only()
    @commands.check(check_if_staff)
    @commands.command(aliases=["iclearreacts", "iclrr"])
    async def clearreactsinteractive(self, ctx):
        """[S] Clears reacts interactively."""
        msg_text = (
            f"React to the reactions you want "
            f"to remove. React to this message when done."
        )
        msg = await ctx.channel.send(msg_text)

        tasks = []

        def check(event):
            # we only care about the user who is clearing reactions
            if event.user_id != ctx.author.id:
                return False
            # this is how the user finishes
            if event.message_id == msg.id:
                return True
            else:
                # remove a reaction
                async def impl():
                    msg = (
                        await self.bot.get_guild(event.guild_id)
                        .get_channel(event.channel_id)
                        .get_message(event.message_id)
                    )

                    def check_emoji(r):
                        if event.emoji.is_custom_emoji() == r.custom_emoji:
                            if event.emoji.is_custom_emoji():
                                return event.emoji.id == r.emoji.id
                            else:
                                # gotta love consistent APIs
                                return event.emoji.name == r.emoji
                        else:
                            return False

                    for reaction in filter(check_emoji, msg.reactions):
                        async for u in reaction.users():
                            await reaction.message.remove_reaction(reaction, u)

                # schedule immediately
                tasks.append(asyncio.create_task(impl()))
                return False

        try:
            await self.bot.wait_for("raw_reaction_add", timeout=120.0, check=check)
        except asyncio.TimeoutError:
            await msg.edit(content=f"Operation timed out.")
        else:
            await asyncio.gather(*tasks)
            await msg.edit(content=f"Operation complete.")


async def setup(bot):
    await bot.add_cog(ModReact(bot))
