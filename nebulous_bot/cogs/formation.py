"""Fleet formation optimizer command: !formation.

The command body is moved verbatim from runbot.py.
"""
import discord
from discord.ext import commands
import logging
import asyncio
import io
import os
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from nebulous_bot.config import Config

# DELIBERATELY EAGER: this import pulls numpy + matplotlib (~100+ MiB RSS)
# at startup, BEFORE the event loop exists. Do NOT make it lazy to save
# memory — v2.3.4 tried exactly that, and the deferred import ran for
# minutes on the 1/8-OCPU VM at first !graph/!formation, starving the event
# loop (blocked heartbeats, gateway resets, every command hung). Paying the
# cost at boot, when nobody is connected, is the stable configuration.
# runbot.py imports this module at module scope for the same reason — the
# cost must land during process startup, not when the cog is added.
from formation_optimizer import (
    optimize_fleet_file,
    create_formation_animation,
)

logger = logging.getLogger('nebulous_bot')


class FormationCog(commands.Cog, name='Formation'):
    """Fleet formation file optimization."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='formation', aliases=['form', 'optimize'])
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def optimize_formation(self, ctx, *, args: str = None):
        """
        Optimize a fleet formation file by compacting ships while maintaining minimum distance.

        Usage: !formation [min_radius_meters] [-skip] [-planar] [-symmetrical] [-arcs]
        - Attach a .fleet XML file to your message
        - Optional: specify minimum radius in meters (default: 350 meters)
        - Optional: use -skip to skip image generation (faster)
        - Optional: use -planar for flat formation facing forward
        - Optional: use -symmetrical for more symmetrical formation
        - Optional: use -arcs to keep forward firing arcs clear for armed ships
        - Returns the optimized fleet file

        Example: !formation 350  (for 350 meters)
        Example: !formation 500 -planar  (planar formation)
        Example: !formation 350 -symmetrical -skip  (symmetrical, skip images)
        Example: !formation 350 -arcs  (keep firing arcs clear)
        """
        # Parse arguments
        skip_images = False
        planar = False
        symmetrical = False
        clear_arcs = False
        min_radius_meters = 350.0

        if args:
            args_lower = args.lower()

            # Check for flags
            if '-skip' in args_lower:
                skip_images = True
                args_lower = args_lower.replace('-skip', '')
            if '-planar' in args_lower:
                planar = True
                args_lower = args_lower.replace('-planar', '')
            if '-symmetrical' in args_lower or '-symmetric' in args_lower:
                symmetrical = True
                args_lower = args_lower.replace('-symmetrical', '').replace('-symmetric', '')
            if '-arcs' in args_lower or '-cleararcs' in args_lower:
                clear_arcs = True
                args_lower = args_lower.replace('-arcs', '').replace('-cleararcs', '')

            # Clean up and parse min_radius_meters
            args_clean = args_lower.strip()
            if args_clean:
                try:
                    min_radius_meters = float(args_clean)
                except ValueError:
                    # If parsing fails, use default
                    pass
        # Check for attachments
        if not ctx.message.attachments:
            embed = discord.Embed(
                title="❌ No File Attached",
                description="Please attach a fleet (.fleet) XML file to your message.",
                color=Config.EMBED_COLOR_NO_SERVERS
            )
            embed.add_field(
                name="Usage",
                value="`!formation [min_radius] [-skip] [-planar] [-symmetrical] [-arcs]`\nAttach a .fleet file to optimize it.\n- `-skip`: Skip image generation\n- `-planar`: Flat formation facing forward\n- `-symmetrical`: More symmetrical formation\n- `-arcs`: Keep forward firing arcs clear for armed ships",
                inline=False
            )
            await ctx.send(embed=embed)
            return

        # Get the first attachment
        attachment = ctx.message.attachments[0]

        # Validate file extension
        if not attachment.filename.lower().endswith('.fleet'):
            embed = discord.Embed(
                title="❌ Invalid File Type",
                description=f"Expected a .fleet file, got: {attachment.filename}",
                color=Config.EMBED_COLOR_NO_SERVERS
            )
            await ctx.send(embed=embed)
            return

        # Validate min_radius_meters (user input is in meters)
        if min_radius_meters <= 0:
            embed = discord.Embed(
                title="❌ Invalid Minimum Radius",
                description="Minimum radius must be greater than 0 meters.",
                color=Config.EMBED_COLOR_NO_SERVERS
            )
            await ctx.send(embed=embed)
            return

        # Show processing message
        processing_msg = await ctx.send("🔄 Processing fleet file...")

        try:
            # Download the file
            file_content = await attachment.read()

            # Create temporary file for input
            with tempfile.NamedTemporaryFile(mode='wb', suffix='.fleet', delete=False) as temp_input:
                temp_input.write(file_content)
                temp_input_path = temp_input.name

            try:
                # Validate XML structure before processing
                try:
                    tree = ET.parse(temp_input_path)
                    root = tree.getroot()

                    # Check for required elements
                    if root.find("Name") is None:
                        raise ValueError("Fleet file missing <Name> element")

                    # Check for at least one Ship element
                    ships = list(root.iter("Ship"))
                    if not ships:
                        raise ValueError("Fleet file contains no <Ship> elements")

                    # Check for InitialFormation elements
                    formations_found = False
                    for ship in ships:
                        if ship.find("InitialFormation") is not None:
                            formations_found = True
                            break

                    if not formations_found:
                        raise ValueError("Fleet file contains no <InitialFormation> elements")

                except ET.ParseError as e:
                    raise ValueError(f"Invalid XML format: {str(e)}") from e

                # Optimize the fleet file
                # Only capture animation if we're generating images
                # min_radius_meters is already in meters (user-facing)
                optimization_result = optimize_fleet_file(
                    temp_input_path,
                    min_distance_meters=min_radius_meters,
                    capture_animation=not skip_images,
                    planar=planar,
                    symmetrical=symmetrical,
                    clear_arcs=clear_arcs
                )

                # Unpack results (with or without animation states)
                if len(optimization_result) == 5:
                    optimized_path, before_positions, after_positions, ship_names, intermediate_states = optimization_result
                else:
                    optimized_path, before_positions, after_positions, ship_names = optimization_result
                    intermediate_states = None

                # Generate GIF animation only if not skipping images
                gif_bytes = None
                gif_path = None

                if not skip_images:
                    # Generate GIF animation (run in executor to avoid blocking)
                    def generate_gif():
                        # Generate GIF animation if we have intermediate states
                        gif_path = None
                        gif_bytes = None
                        if intermediate_states:
                            try:
                                # Create temporary file for GIF
                                gif_temp = tempfile.NamedTemporaryFile(suffix='.gif', delete=False)
                                gif_path = gif_temp.name
                                gif_temp.close()

                                # Generate GIF from intermediate states (all positions already in meters)
                                create_formation_animation(
                                    before_positions,
                                    intermediate_states,
                                    ship_names,
                                    min_radius_meters,
                                    output_path=gif_path,
                                    fps=10,
                                    duration_ms=100
                                )

                                # Read GIF bytes
                                with open(gif_path, 'rb') as f:
                                    gif_bytes = f.read()
                            except Exception as gif_error:
                                logger.warning(f"Failed to generate GIF animation: {gif_error}")
                                # Continue without GIF if generation fails
                        else:
                            logger.warning("No intermediate states available for GIF generation")

                        return gif_bytes, gif_path

                    import concurrent.futures
                    loop = asyncio.get_event_loop()
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        gif_bytes, gif_path = await loop.run_in_executor(executor, generate_gif)

                # Read the optimized file
                with open(optimized_path, 'rb') as f:
                    optimized_content = f.read()

                # Create Discord file objects
                optimized_filename = attachment.filename.replace('.fleet', f'_Optimized_{int(min_radius_meters)}m.fleet')
                discord_file = discord.File(
                    io.BytesIO(optimized_content),
                    filename=optimized_filename
                )

                # Prepare files list
                files_to_send = [discord_file]

                # Add GIF if generated successfully and not skipping images
                discord_gif_file = None
                if not skip_images:
                    if gif_bytes:
                        gif_filename = attachment.filename.replace('.fleet', f'_animation_{int(min_radius_meters)}m.gif')
                        discord_gif_file = discord.File(
                            io.BytesIO(gif_bytes),
                            filename=gif_filename
                        )
                        files_to_send.append(discord_gif_file)
                    else:
                        # If GIF generation failed, send error message
                        embed_error = discord.Embed(
                            title="⚠️ Optimization Complete",
                            description="Fleet optimized but animation generation failed.",
                            color=Config.EMBED_COLOR_NO_SERVERS
                        )
                        await processing_msg.edit(content="", embed=embed_error)
                        return

                # Create success embed
                variant_info = []
                if planar:
                    variant_info.append("Planar")
                if symmetrical:
                    variant_info.append("Symmetrical")
                variant_text = f" ({', '.join(variant_info)})" if variant_info else ""

                embed = discord.Embed(
                    title="✅ Formation Optimized",
                    description=f"Fleet formation optimized with minimum radius of **{min_radius_meters:.0f} meters**{variant_text}.",
                    color=Config.EMBED_COLOR,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(
                    name="Original File",
                    value=attachment.filename,
                    inline=True
                )
                embed.add_field(
                    name="Minimum Radius",
                    value=f"{min_radius_meters:.0f} meters",
                    inline=True
                )
                embed.add_field(
                    name="Ships Processed",
                    value=str(len(ships)),
                    inline=True
                )
                if variant_info:
                    embed.add_field(
                        name="Formation Variant",
                        value=", ".join(variant_info),
                        inline=False
                    )

                # Set GIF as image in embed (only if not skipping)
                if not skip_images and gif_bytes:
                    gif_filename = attachment.filename.replace('.fleet', f'_animation_{int(min_radius_meters)}m.gif')
                    embed.set_image(url=f"attachment://{gif_filename}")

                # Update footer based on whether images were generated
                if skip_images:
                    embed.set_footer(text="The optimized fleet file is attached below")
                else:
                    embed.set_footer(text="The optimized fleet file and animation GIF are attached below")

                # Delete processing message and send result
                await processing_msg.delete()
                await ctx.send(embed=embed, files=files_to_send)

                # Clean up temporary GIF file
                if gif_path and os.path.exists(gif_path):
                    try:
                        os.unlink(gif_path)
                    except Exception as cleanup_error:
                        logger.warning(f"Failed to cleanup GIF temp file: {cleanup_error}")

            finally:
                # Clean up temporary files
                try:
                    os.unlink(temp_input_path)
                    if os.path.exists(optimized_path):
                        os.unlink(optimized_path)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temp files: {cleanup_error}")

        except ValueError as e:
            # Validation errors
            embed = discord.Embed(
                title="❌ Invalid Fleet File",
                description=str(e),
                color=Config.EMBED_COLOR_NO_SERVERS
            )
            await processing_msg.edit(content="", embed=embed)
        except Exception as e:
            # Other errors
            logger.error(f"Error optimizing formation: {e}", exc_info=True)
            embed = discord.Embed(
                title="❌ Processing Error",
                description=f"Failed to optimize fleet file: {str(e)}",
                color=Config.EMBED_COLOR_NO_SERVERS
            )
            await processing_msg.edit(content="", embed=embed)
