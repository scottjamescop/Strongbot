import discord
from discord.ext import commands, tasks
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import random

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Data structure to store the weight lifted by users
user_weights = {}
weekly_goal = 0
total_weight = 0

# List of comparisons (you can add more)
comparisons = [
    ("an elephant", 12000),  # weight in pounds
        ("a car", 4000),
            ("the Eiffel Tower", 22000000),
                ("a blue whale", 330000),
                    ("a house", 100000),
                    ]

                    # Helper function to convert weight to large objects
                    def compare_weight(weight):
                        for obj, obj_weight in comparisons:
                                if weight < obj_weight:
                                            return f"the weight of {weight // obj_weight} {obj}(s)"
                                                return "something incredibly massive!"


                                                # Command for users to log their weight lifted
                                                @bot.command(name="log")
                                                async def log_weight(ctx, weight: float):
                                                    global total_weight
                                                        if ctx.author.id not in user_weights:
                                                                user_weights[ctx.author.id] = 0
                                                                    user_weights[ctx.author.id] += weight
                                                                        total_weight += weight
                                                                            await ctx.send(f"{ctx.author.mention} logged {weight} lbs! Total logged: {user_weights[ctx.author.id]} lbs")


                                                                            # Command for admin to set the weekly goal
                                                                            @bot.command(name="set_goal")
                                                                            @commands.has_permissions(administrator=True)
                                                                            async def set_goal(ctx, goal: float):
                                                                                global weekly_goal
                                                                                    weekly_goal = goal
                                                                                        await ctx.send(f"The weekly goal is set to {weekly_goal} lbs!")


                                                                                        # Weekly report task
                                                                                        @tasks.loop(hours=168)  # Executes every 168 hours (weekly)
                                                                                        async def weekly_report():
                                                                                            guild = bot.guilds[0]  # Assuming the bot is in one server
                                                                                                channel = discord.utils.get(guild.channels, name="general")  # Modify channel name if needed
                                                                                                    if channel:
                                                                                                            progress = (total_weight / weekly_goal) * 100 if weekly_goal > 0 else 0
                                                                                                                    comparison = compare_weight(total_weight)
                                                                                                                            await channel.send(
                                                                                                                                        f"Weekly progress report:\n"
                                                                                                                                                    f"Total weight lifted: {total_weight} lbs\n"
                                                                                                                                                                f"That's like {comparison}!\n"
                                                                                                                                                                            f"Goal progress: {progress:.2f}% of the {weekly_goal} lbs goal!"
                                                                                                                                                                                    )
                                                                                                                                                                                            # Reset for the next week
                                                                                                                                                                                                    reset_weekly_totals()


                                                                                                                                                                                                    # Helper function to reset weekly totals
                                                                                                                                                                                                    def reset_weekly_totals():
                                                                                                                                                                                                        global total_weight, user_weights
                                                                                                                                                                                                            total_weight = 0
                                                                                                                                                                                                                user_weights = {}


                                                                                                                                                                                                                # Schedule the weekly report to run every Sunday at 9 a.m.
                                                                                                                                                                                                                scheduler = AsyncIOScheduler()
                                                                                                                                                                                                                scheduler.add_job(weekly_report, 'cron', day_of_week='sun', hour=9)
                                                                                                                                                                                                                scheduler.start()


                                                                                                                                                                                                                # Event to signal bot is ready
                                                                                                                                                                                                                @bot.event
                                                                                                                                                                                                                async def on_ready():
                                                                                                                                                                                                                    print(f"Bot is ready and logged in as {bot.user}!")


                                                                                                                                                                                                                    # Error handler for missing permissions (e.g., non-admins trying to set goal)
                                                                                                                                                                                                                    @bot.event
                                                                                                                                                                                                                    async def on_command_error(ctx, error):
                                                                                                                                                                                                                        if isinstance(error, commands.MissingPermissions):
                                                                                                                                                                                                                                await ctx.send(f"{ctx.author.mention}, you don't have the required permissions to run this command.")


                                                                                                                                                                                                                                # Run the bot
                                                                                                                                                                                                                                bot.run('YOUR_BOT_TOKEN')