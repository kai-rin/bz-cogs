import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import discord
from redbot.core import checks, commands
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate

from aiuser.config.defaults import DEFAULT_LLM_MODEL, DEFAULT_IMAGES_SCAN_MODEL
from aiuser.core.openai_utils import setup_openai_client
from aiuser.settings.utilities import get_tokens, truncate_prompt
from aiuser.types.abc import MixinMeta
from aiuser.utils.utilities import is_using_openrouter_endpoint

logger = logging.getLogger("red.bz_cogs.aiuser")


class OwnerSettings(MixinMeta):
    @commands.group(aliases=["ai_userowner"])
    @checks.is_owner()
    async def aiuserowner(self, _):
        """For some settings that apply bot-wide."""
        pass

    @aiuserowner.command(name="maxpromptlength")
    async def max_prompt_length(self, ctx: commands.Context, length: int):
        """Sets the maximum character length of a prompt that can set by admins in any server.

            (Does not apply to already set prompts, only new ones)
        """
        if length < 1:
            return await ctx.send("Please enter a positive integer.")
        await self.config.max_prompt_length.set(length)
        embed = discord.Embed(
            title="The maximum prompt length is now:",
            description=f"{length}",
            color=await ctx.embed_color(),
        )
        return await ctx.send(embed=embed)

    @aiuserowner.command(name="maxtopiclength")
    async def max_random_prompt_length(self, ctx: commands.Context, length: int):
        """Sets the maximum character length of a random prompt that can set by any server.

            (Does not apply to already set prompts, only new ones)
        """
        if length < 1:
            return await ctx.send("Please enter a positive integer.")
        await self.config.max_random_prompt_length.set(length)
        embed = discord.Embed(
            title="The maximum topic length is now:",
            description=f"{length}",
            color=await ctx.embed_color(),
        )
        return await ctx.send(embed=embed)

    @aiuserowner.command()
    async def endpoint(self, ctx: commands.Context, url: Optional[str]):
        """Sets the OpenAI endpoint to a custom one (must be OpenAI API compatible)

        Reset to official OpenAI endpoint with `[p]aiuseradmin endpoint clear`
        """

        if url == "openrouter":
            url = "https://openrouter.ai/api/v1/"

        if url and url.lower() in ["xai", "x.ai"]:
            url = "https://api.x.ai/v1/"

        if not url or url in ["clear", "reset", "openai"]:
            await self.config.custom_openai_endpoint.set(None)
            url = None
        else:
            await self.config.custom_openai_endpoint.set(url)

        self.openai_client = await setup_openai_client(self.bot, self.config)

        chat_model = DEFAULT_LLM_MODEL
        image_model = DEFAULT_IMAGES_SCAN_MODEL

        if (is_using_openrouter_endpoint(self.openai_client)):
            chat_model = "openai/gpt-4o-mini"
            image_model = "openai/gpt-4o-mini"

        embed = discord.Embed(
            title="Bot Custom OpenAI endpoint", color=await ctx.embed_color()
        )
        embed.add_field(
            name="🔄 Reset",
            value=f"Per-server models have been set to use `{chat_model}` for chat \n and `{image_model}` for LLM image scan mode.",
            inline=False,
        )

        guilds_with_parameters = []
        for guild_id in await self.config.all_guilds():
            await self.config.guild_from_id(guild_id).model.set(chat_model)
            await self.config.guild_from_id(guild_id).scan_images_model.set(image_model)
            if await self.config.guild_from_id(guild_id).parameters():
                guilds_with_parameters.append(str(self.bot.get_guild(guild_id).name))

        if guilds_with_parameters:
            embed.add_field(
                name=":warning: Caution",
                value=f"Custom parameters have been set in the following guilds: `{', '.join(guilds_with_parameters)}`\nThey may not work with the new endpoint!",
                inline=False,
            )

        if url:
            embed.description = f"Endpoint set to {url}."
            embed.add_field(
                name="❗ Third Party Models",
                value="Third party models may have undesirable results with this cog, compared to OpenAI's LLMs.",
                inline=False,
            )
        else:
            embed.description = "Endpoint reset back to offical OpenAI endpoint."

        await ctx.send(embed=embed)

    @aiuserowner.command()
    async def timeout(self, ctx: commands.Context, seconds: int):
        """ Sets the request timeout to the OpenAI endpoint """

        if seconds < 1:
            return await ctx.send(":warning: Please enter a positive integer.")

        await self.config.openai_endpoint_request_timeout.set(seconds)
        await self.initialize_openai_client()

        embed = discord.Embed(
            title="The request timeout is now:",
            description=f"{seconds} seconds",
            color=await ctx.embed_color(),
        )
        return await ctx.send(embed=embed)

    @aiuserowner.command(name="exportconfig")
    async def export_config(self, ctx: commands.Context):
        """Exports the current config to a json file

           :warning: JSON backend only
        """
        path = Path(cog_data_path(self) / "settings.json")

        if not path.exists():
            return await ctx.send(":warning: Export is only supported for json backends")

        await ctx.send(
            file=discord.File(path, filename="aiuser_config.json")
        )
        await ctx.tick()

    @aiuserowner.command(name="importconfig")
    async def import_config(self, ctx: commands.Context):
        """ Imports a config from json file (:warning: No checks are done)

            Make sure your new config is valid, and the old config is backed up.

           :warning: JSON backend only
        """
        if not ctx.message.attachments:
            return await ctx.send(":warning: No file was attached.")

        file = ctx.message.attachments[0]
        try:
            new_config = json.loads(await file.read())
        except json.JSONDecodeError:
            return await ctx.send(":warning: Invalid JSON format!")

        path = Path(cog_data_path(self) / "settings.json")

        if not path.exists():
            return await ctx.send(":warning: Import is only supported for json backends")

        embed = discord.Embed(
            title="Have you backed up your current config?",
            description=f":warning: This will overwrite the current config, and you will lose existing settings! \
                \n :warning: You may also break the cog or bot, if the config is invalid. \
                \n To fix, make sure you can access the config file: \n `{path}`",
            color=await ctx.embed_color())
        confirm = await ctx.send(embed=embed)
        start_adding_reactions(confirm, ReactionPredicate.YES_OR_NO_EMOJIS)
        pred = ReactionPredicate.yes_or_no(confirm, ctx.author)
        try:
            await ctx.bot.wait_for("reaction_add", timeout=30.0, check=pred)
        except asyncio.TimeoutError:
            return await confirm.edit(embed=discord.Embed(title="Cancelled.", color=await ctx.embed_color()))
        if pred.result is False:
            return await confirm.edit(embed=discord.Embed(title="Cancelled.", color=await ctx.embed_color()))

        with path.open("w") as f:
            json.dump(new_config, f, indent=4)

        return await confirm.edit(embed=discord.Embed(
            title="Overwritten!",
            description="You will need to restart the bot for the changes to take effect.",
            color=await ctx.embed_color()))

    @aiuserowner.command(name="prompt")
    async def global_prompt(self, ctx: commands.Context, *, prompt: Optional[str]):
        """ Set the global default prompt for aiuser.

            Leave blank to delete the currently set global prompt, and use the build-in default prompt.

            **Arguments**
                - `prompt` The prompt to set.
        """
        if not prompt and ctx.message.attachments:
            if not ctx.message.attachments[0].filename.endswith(".txt"):
                return await ctx.send(":warning: Invalid attachment. Must be a `.txt` file.")
            prompt = (await ctx.message.attachments[0].read()).decode("utf-8")

        if not prompt:
            await self.config.custom_text_prompt.set(None)
            return await ctx.send("The global prompt is now reset to the default prompt")

        await self.config.custom_text_prompt.set(prompt)

        embed = discord.Embed(
            title="The global prompt is now changed to:",
            description=f"{truncate_prompt(prompt)}",
            color=await ctx.embed_color())
        embed.add_field(name="Tokens", value=await get_tokens(self.config, ctx, prompt))
        return await ctx.send(embed=embed)
