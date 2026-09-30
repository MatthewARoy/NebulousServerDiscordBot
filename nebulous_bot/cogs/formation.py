"""Fleet formation optimizer command exposed through prefix and slash UI."""

import asyncio
import io
import logging
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

import discord
from discord import app_commands
from discord.ext import commands

from nebulous_bot.config import Config

# DELIBERATELY EAGER: this import pulls numpy + matplotlib (~100+ MiB RSS)
# at startup, BEFORE the event loop exists. Do NOT make it lazy to save
# memory — v2.3.4 tried exactly that, and the deferred import ran for
# minutes on the 1/8-OCPU VM while holding the GIL.
from formation_optimizer import create_formation_animation, optimize_fleet_file

logger = logging.getLogger('nebulous_bot')

MAX_FLEET_BYTES = 2 * 1024 * 1024
MAX_XML_DEPTH = 64
MAX_XML_ELEMENTS = 100_000
MAX_SHIPS = 100
MAX_HULL_SOCKETS = 10_000
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_ANIMATION_STATES = 5
ANIMATION_FPS = 2
MIN_RADIUS_METERS = 1.0
MAX_RADIUS_METERS = 5_000.0


class FormationOptions(NamedTuple):
    min_radius_meters: float
    skip_images: bool
    planar: bool
    symmetrical: bool
    clear_arcs: bool


class FormationResult(NamedTuple):
    optimized_content: bytes
    gif_bytes: Optional[bytes]
    ship_count: int


def parse_formation_options(raw: Optional[str]) -> FormationOptions:
    """Parse the legacy free-form flags retained for prefix compatibility."""
    min_radius_meters = 350.0
    flags = {
        '-skip': False,
        '-planar': False,
        '-symmetrical': False,
        '-arcs': False,
    }
    radius_seen = False

    for token in (raw or '').lower().split():
        canonical = {'-symmetric': '-symmetrical', '-cleararcs': '-arcs'}.get(token, token)
        if canonical in flags:
            flags[canonical] = True
            continue
        if radius_seen:
            raise ValueError(f"Unknown formation option: {token}")
        try:
            min_radius_meters = float(token)
        except ValueError as exc:
            raise ValueError(f"Unknown formation option: {token}") from exc
        radius_seen = True

    if not MIN_RADIUS_METERS <= min_radius_meters <= MAX_RADIUS_METERS:
        raise ValueError(
            f"Minimum radius must be between {MIN_RADIUS_METERS:.0f} and "
            f"{MAX_RADIUS_METERS:.0f} meters."
        )
    return FormationOptions(
        min_radius_meters=min_radius_meters,
        skip_images=flags['-skip'],
        planar=flags['-planar'],
        symmetrical=flags['-symmetrical'],
        clear_arcs=flags['-arcs'],
    )


def validate_fleet_xml(content: bytes) -> int:
    """Validate a bounded fleet document and return its ship count."""
    if not content:
        raise ValueError("Fleet file is empty.")
    if len(content) > MAX_FLEET_BYTES:
        raise ValueError(f"Fleet file exceeds the {MAX_FLEET_BYTES // (1024 * 1024)} MiB limit.")

    # XML declarations use ASCII code points even in UTF-16/32. Remove the
    # interleaved NUL bytes before checking so an encoding change cannot
    # bypass the explicit DTD/entity ban.
    lowered = content.lower().replace(b'\x00', b'')
    if b'<!doctype' in lowered or b'<!entity' in lowered:
        raise ValueError("Fleet XML declarations and entities are not supported.")

    depth = 0
    element_count = 0
    ship_count = 0
    socket_count = 0
    try:
        parser = ET.iterparse(io.BytesIO(content), events=('start', 'end'))
        for event, element in parser:
            if event == 'start':
                depth += 1
                element_count += 1
                if depth > MAX_XML_DEPTH:
                    raise ValueError(f"Fleet XML exceeds the maximum depth of {MAX_XML_DEPTH}.")
                if element_count > MAX_XML_ELEMENTS:
                    raise ValueError(f"Fleet XML exceeds the {MAX_XML_ELEMENTS:,}-element limit.")
                local_name = element.tag.rsplit('}', 1)[-1]
                if local_name == 'Ship':
                    ship_count += 1
                    if ship_count > MAX_SHIPS:
                        raise ValueError(f"Fleet contains more than {MAX_SHIPS} ships.")
                elif local_name == 'HullSocket':
                    socket_count += 1
                    if socket_count > MAX_HULL_SOCKETS:
                        raise ValueError(f"Fleet contains more than {MAX_HULL_SOCKETS:,} hull sockets.")
            else:
                depth -= 1
        root = parser.root
    except ET.ParseError as exc:
        raise ValueError(f"Invalid fleet XML: {exc}") from exc

    if root.find('Name') is None:
        raise ValueError("Fleet file is missing its <Name> element.")
    ships = list(root.iter('Ship'))
    if not ships:
        raise ValueError("Fleet file contains no <Ship> elements.")
    if not any(ship.find('InitialFormation') is not None for ship in ships):
        raise ValueError("Fleet file contains no <InitialFormation> elements.")
    return ship_count


def _unlink(path: Optional[str]) -> None:
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError as exc:
            logger.warning("Failed to clean up temporary file %s: %s", path, exc)


def _sample_animation_states(states: list, limit: int = MAX_ANIMATION_STATES) -> list:
    """Keep animation memory bounded while retaining its first and last state."""
    if len(states) <= limit:
        return states
    step = math.ceil((len(states) - 1) / (limit - 1))
    sampled = states[::step]
    if sampled[-1] is not states[-1]:
        sampled.append(states[-1])
    return sampled[:limit - 1] + [states[-1]] if len(sampled) > limit else sampled


def process_formation(content: bytes, options: FormationOptions) -> FormationResult:
    """Run validation, optimization, and optional rendering off the event loop."""
    ship_count = validate_fleet_xml(content)
    input_path = None
    optimized_path = None
    gif_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.fleet', delete=False) as temp_input:
            temp_input.write(content)
            input_path = temp_input.name

        optimization_result = optimize_fleet_file(
            input_path,
            min_distance_meters=options.min_radius_meters,
            capture_animation=not options.skip_images,
            planar=options.planar,
            symmetrical=options.symmetrical,
            clear_arcs=options.clear_arcs,
        )
        if len(optimization_result) == 5:
            optimized_path, before, _after, ship_names, states = optimization_result
        else:
            optimized_path, before, _after, ship_names = optimization_result
            states = None

        optimized_content = Path(optimized_path).read_bytes()
        if len(optimized_content) > MAX_OUTPUT_BYTES:
            raise ValueError("Optimized fleet exceeds Discord's safe upload limit.")

        gif_bytes = None
        if not options.skip_images and states:
            animation_states = _sample_animation_states(states)
            with tempfile.NamedTemporaryFile(suffix='.gif', delete=False) as gif_temp:
                gif_path = gif_temp.name
            try:
                create_formation_animation(
                    before,
                    animation_states,
                    ship_names,
                    options.min_radius_meters,
                    output_path=gif_path,
                    fps=ANIMATION_FPS,
                    duration_ms=100,
                )
                rendered = Path(gif_path).read_bytes()
                if len(optimized_content) + len(rendered) <= MAX_OUTPUT_BYTES:
                    gif_bytes = rendered
                else:
                    logger.warning("Formation attachments exceeded the safe upload limit; omitting GIF")
            except Exception as exc:
                logger.warning("Failed to generate formation GIF: %s", exc)

        return FormationResult(optimized_content, gif_bytes, ship_count)
    finally:
        _unlink(gif_path)
        _unlink(optimized_path)
        _unlink(input_path)


class FormationCog(commands.Cog, name='Formation'):
    """Fleet formation file optimization."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._optimization_lock = asyncio.Lock()

    def _finish_cancelled_worker(self, worker: asyncio.Task) -> None:
        """Observe a detached worker's result and release its capacity."""
        try:
            error = worker.exception()
            if error is not None:
                logger.error(
                    "Cancelled formation request's worker failed",
                    exc_info=(type(error), error, error.__traceback__),
                )
        except asyncio.CancelledError:
            logger.warning("Formation worker task was cancelled during shutdown")
        finally:
            if self._optimization_lock.locked():
                self._optimization_lock.release()

    @commands.hybrid_command(
        name='formation',
        aliases=['form', 'optimize'],
        description='Compact ship positions in an attached NEBULOUS fleet file.',
    )
    @app_commands.describe(
        attachment='The .fleet file to optimize',
        options='Optional radius and flags: 350 -skip -planar -symmetrical -arcs',
    )
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def optimize_formation(
        self,
        ctx,
        attachment: Optional[discord.Attachment] = None,
        *,
        options: Optional[str] = None,
    ):
        """Optimize an attached fleet formation while maintaining minimum distance.

        Usage: !formation [min_radius_meters] [-skip] [-planar] [-symmetrical] [-arcs]
        - Attach a .fleet XML file to your message
        - Optional: specify minimum radius in meters (default: 350 meters)
        - Optional: use -skip to skip image generation (faster)
        - Optional: use -planar for flat formation facing forward
        - Optional: use -symmetrical for more symmetrical formation
        - Optional: use -arcs to keep forward firing arcs clear for armed ships

        Example: !formation 350
        Example: !formation 500 -planar
        """
        if attachment is None:
            await ctx.send(
                embed=discord.Embed(
                    title="❌ No File Attached",
                    description="Attach a `.fleet` XML file and try `/formation` again.",
                    color=Config.EMBED_COLOR_NO_SERVERS,
                )
            )
            return

        safe_filename = Path(attachment.filename).name[:100]
        if not safe_filename.lower().endswith('.fleet'):
            await ctx.send(
                embed=discord.Embed(
                    title="❌ Invalid File Type",
                    description=f"Expected a `.fleet` file, got `{safe_filename}`.",
                    color=Config.EMBED_COLOR_NO_SERVERS,
                )
            )
            return
        if attachment.size > MAX_FLEET_BYTES:
            await ctx.send(
                f"❌ Fleet files are limited to {MAX_FLEET_BYTES // (1024 * 1024)} MiB."
            )
            return

        try:
            parsed = parse_formation_options(options)
        except ValueError as exc:
            await ctx.send(f"❌ {exc}")
            return

        # Fail fast instead of retaining one attachment per waiting user on
        # the small production VM. The check and uncontended acquire execute
        # without an intervening event-loop suspension.
        if self._optimization_lock.locked():
            await ctx.send(
                "⏳ Another fleet is being optimized. Please try again shortly.",
                ephemeral=ctx.interaction is not None,
            )
            return
        await self._optimization_lock.acquire()

        processing_msg = None
        worker = None
        release_in_callback = False

        try:
            await ctx.defer()
            if ctx.interaction is None:
                processing_msg = await ctx.send("🔄 Processing fleet file...")

            content = await attachment.read()
            if len(content) > MAX_FLEET_BYTES:
                raise ValueError(
                    f"Fleet file exceeds the {MAX_FLEET_BYTES // (1024 * 1024)} MiB limit."
                )
            worker = asyncio.create_task(asyncio.to_thread(process_formation, content, parsed))
            try:
                result = await asyncio.shield(worker)
            except asyncio.CancelledError:
                # Cancelling to_thread only cancels its awaiter; the worker
                # keeps running. Transfer lock release to its completion so a
                # reconnect/cancel cannot start a second optimizer alongside it.
                if not worker.done():
                    worker.add_done_callback(self._finish_cancelled_worker)
                    release_in_callback = True
                raise

            stem = safe_filename[:-6]
            optimized_name = f'{stem}_Optimized_{int(parsed.min_radius_meters)}m.fleet'
            files = [discord.File(io.BytesIO(result.optimized_content), filename=optimized_name)]
            if result.gif_bytes:
                gif_name = f'{stem}_animation_{int(parsed.min_radius_meters)}m.gif'
                files.append(discord.File(io.BytesIO(result.gif_bytes), filename=gif_name))

            variants = []
            if parsed.planar:
                variants.append('Planar')
            if parsed.symmetrical:
                variants.append('Symmetrical')
            if parsed.clear_arcs:
                variants.append('Clear firing arcs')
            embed = discord.Embed(
                title="✅ Formation Optimized",
                description=(
                    f"Fleet formation optimized with a minimum radius of "
                    f"**{parsed.min_radius_meters:.0f} meters**."
                ),
                color=Config.EMBED_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Original File", value=safe_filename, inline=True)
            embed.add_field(name="Ships Processed", value=str(result.ship_count), inline=True)
            if variants:
                embed.add_field(name="Formation Variant", value=', '.join(variants), inline=False)
            if result.gif_bytes:
                embed.set_image(url=f"attachment://{files[1].filename}")
            embed.set_footer(
                text="Optimized fleet and animation attached"
                if result.gif_bytes else "Optimized fleet attached"
            )
            if processing_msg:
                await processing_msg.delete()
            await ctx.send(embed=embed, files=files)
        except ValueError as exc:
            error = discord.Embed(
                title="❌ Invalid Fleet File",
                description=str(exc)[:500],
                color=Config.EMBED_COLOR_NO_SERVERS,
            )
            if processing_msg:
                await processing_msg.edit(content="", embed=error)
            else:
                await ctx.send(embed=error)
        except Exception as exc:
            logger.error("Error optimizing formation: %s", exc, exc_info=True)
            error = discord.Embed(
                title="❌ Processing Error",
                description="The fleet could not be optimized. Check the file and try again.",
                color=Config.EMBED_COLOR_NO_SERVERS,
            )
            if processing_msg:
                await processing_msg.edit(content="", embed=error)
            else:
                await ctx.send(embed=error)
        finally:
            if not release_in_callback and self._optimization_lock.locked():
                self._optimization_lock.release()
