import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View
import database

class RankingView(View):
    def __init__(self, author_id: int, bot: commands.Bot, is_fixed: bool = False, fixed_mode: str | None = None):
        # Para views fixas, não queremos timeout (permanece ativo)
        timeout = None if is_fixed else 900
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.bot = bot
        self.is_fixed = is_fixed
        self.fixed_mode = fixed_mode
        self.current_mode = None  # Para rastrear o modo atual

        # Se for ranking fixo por modo (fixed_mode informado), remove botões de movimentação
        # Isso inclui botões de modo e os botões de navegação (Voltar / Fechar)
        if is_fixed and fixed_mode is not None:
            # A lista self.children pode ser mutada ao iterar, então convertemos para lista estática
            for item in list(self.children):
                try:
                    cid = getattr(item, 'custom_id', None)
                    if cid and cid.startswith('rank_'):
                        # Remove todos os botões que começam com rank_ (modes e navegação)
                        self.remove_item(item)
                except Exception:
                    continue
        elif is_fixed:
            # Compatibilidade legada: remove apenas o botão fechar
            for item in list(self.children):
                if getattr(item, 'custom_id', None) == "rank_close":
                    try:
                        self.remove_item(item)
                    except Exception:
                        pass
                    break

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Para ranking fixo, permite qualquer usuário
        if self.is_fixed:
            return True

        if self.author_id is not None and interaction.user.id != self.author_id:
            await interaction.response.send_message("Você não pode usar estes botões.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        # Verifica se a mensagem ainda existe antes de tentar editar
        if hasattr(self, 'message') and self.message:
            try:
                await self.message.edit(content="⏰ Este menu de rankings expirou. Use `/rankings` para abri-lo novamente.", view=None)
            except discord.NotFound:
                pass # A mensagem já foi deletada, não há nada a fazer.

    async def handle_expired_interaction(self, interaction: discord.Interaction, mode: str = None):
        """Recria a view quando uma interação expirada é detectada."""
        try:
            # Cria uma nova interação de followup em vez de tentar editar
            if mode:
                # Se estava mostrando um ranking específico, recria isso
                await self.show_ranking_followup(interaction, mode)
            else:
                # Se estava no menu principal, recria o menu
                await self.show_menu_followup(interaction)

        except Exception as e:
            print(f"Erro ao recriar view expirada: {e}")
            try:
                await interaction.followup.send("❌ Ocorreu um erro ao recriar o menu. Use `/rankings` para abrir um novo.", ephemeral=True)
            except:
                pass

    async def show_menu_followup(self, interaction: discord.Interaction):
        """Mostra o menu inicial via followup quando a interação original expirou."""
        embed = discord.Embed(
            title="Legion Chess | Rankings",
            description="Selecione um modo para ver seu Ranking.",
            color = 0xCD0000
        )
        await interaction.followup.send(embed=embed, view=self, ephemeral=True)

    async def show_ranking_followup(self, interaction: discord.Interaction, mode: str):
        """Mostra o ranking via followup quando a interação original expirou."""
        # Criar embed de banner
        banner_embed = discord.Embed(color = 0xCD0000)

        # Definir imagem do banner baseada no modo
        banner_urls = {
            "bullet": "https://media.discordapp.net/attachments/1393788085455687802/1434146966593474641/gif_torneios_Copy_Copy_C936744.png?ex=69089671&is=690744f1&hm=4abe071b49778bd87b9f48a2336984cd5ab746c7eb19dd19efef0badddbc5154&=&format=webp&quality=lossless&width=1565&height=569",
            "blitz": "https://cdn.discordapp.com/attachments/1393788085455687802/1434147563023499405/Novo_projeto_14_626ADA3.png?ex=69089700&is=69074580&hm=db4ed8395d45fcf08b1e3df96309c00470fc10b285802bf79ad95826637d5ca6&",
            "rapid": "https://cdn.discordapp.com/attachments/1393788085455687802/1434146976177459312/gif_torneios_068B442.png?ex=69089674&is=690744f4&hm=e28e5146a72f1fd98052ee04e84b812b1c9ffb2c42cb8c9186920f10a8544c46&",
            "classic": "https://cdn.discordapp.com/attachments/1393788085455687802/1434146986218487899/gif_torneios_Copy_845CA62.png?ex=69089676&is=690744f6&hm=669035f2b768eca96eac0869f7b8ba02e143c87f3da2f127a2b844b9b2880532&"
        }
        banner_embed.set_image(url=banner_urls.get(mode, banner_urls["bullet"]))

        try:
            top_players = await database.get_top_players_by_mode(mode, 8)

            if not top_players:
                embed = discord.Embed(
                    title=f"🏆 | Ranking {mode.capitalize()}",
                    description=f"Não há jogadores suficientes no ranking de {mode} ainda.",
                    color = 0xCD0000
                )
                await interaction.followup.send(embeds=[banner_embed, embed], view=self, ephemeral=True)
                return

            # Criar lista de embeds: banner + um embed por jogador
            embeds = [banner_embed]

            for i, player in enumerate(top_players, 1):
                discord_id = player.get('discord_id')
                discord_username = player.get('discord_username', 'Desconhecido')

                if discord_id:
                    discord_mention = f"<@{discord_id}>"
                else:
                    discord_mention = discord_username

                if i <= 3:
                    medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
                    title = f"{medal} #{i} - {discord_username}"
                    color = 0xFFD700 if i == 1 else 0xC0C0C0 if i == 2 else 0xCD7F32
                else:
                    title = f"#{i} - {discord_username}"
                    color = 0xCD0000

                player_embed = discord.Embed(title=title, color=color)

                # Obter avatar do usuário
                if discord_id:
                    try:
                        member = interaction.guild.get_member(int(discord_id)) if interaction.guild else None
                        if member:
                            avatar_url = member.display_avatar.url
                        else:
                            user = await self.bot.fetch_user(int(discord_id))
                            if user:
                                avatar_url = user.display_avatar.url

                        if avatar_url:
                            player_embed.set_thumbnail(url=avatar_url)
                    except Exception as e:
                        print(f"Erro ao obter avatar do usuário {discord_id}: {e}")

                lichess_username = player.get('lichess_username', 'Sem Lichess')
                lichess_link = f"https://lichess.org/@/{lichess_username}" if lichess_username != 'Sem Lichess' else 'Sem Lichess'

                description = f"👤 ➜ Usuário: {discord_mention}\n🔗 ➜ Lichess: [{lichess_username}]({lichess_link})\n⭐ ➜ Rating: **{player['rating']}**\n🎯 ➜ Modo: {mode.capitalize()}"

                player_embed.description = description
                embeds.append(player_embed)

            # Criar embed separado para o footer
            footer_embed = discord.Embed(color = 0xCD0000)
            footer_embed.set_footer(text="💡 O rating é atualizado a cada partida | Use os botões para ver outros modos.")
            embeds.append(footer_embed)

            await interaction.followup.send(embeds=embeds, view=self, ephemeral=True)

        except Exception as e:
            print(f"ERRO CRÍTICO AO BUSCAR RANKING ({mode}): {type(e).__name__} - {e}")

            error_embed = discord.Embed(
                title="❌ Erro ao Carregar Ranking",
                description="Ocorreu um erro inesperado ao buscar os dados do ranking. Tente novamente mais tarde.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
            self.stop()

    # Mostra o menu inicial (usado pelo botão "Voltar")
    async def show_menu(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Legion Chess | Rankings",
            description="Selecione um modo para ver seu Ranking.",
            color = 0xCD0000
        )
        await interaction.edit_original_response(embed=embed, view=self)

    # --- MUDANÇA PRINCIPAL: Adicionado tratamento de erro completo ---
    async def show_ranking(self, interaction: discord.Interaction, mode: str):
        # Criar embed de banner
        banner_embed = discord.Embed(
        color = 0xCD0000
        )

        # Definir imagem do banner baseada no modo
        banner_urls = {
            "bullet": "https://media.discordapp.net/attachments/1393788085455687802/1434146966593474641/gif_torneios_Copy_Copy_C936744.png?ex=69089671&is=690744f1&hm=4abe071b49778bd87b9f48a2336984cd5ab746c7eb19dd19efef0badddbc5154&=&format=webp&quality=lossless&width=1565&height=569",
            "blitz": "https://cdn.discordapp.com/attachments/1393788085455687802/1434147563023499405/Novo_projeto_14_626ADA3.png?ex=69089700&is=69074580&hm=db4ed8395d45fcf08b1e3df96309c00470fc10b285802bf79ad95826637d5ca6&",
            "rapid": "https://cdn.discordapp.com/attachments/1393788085455687802/1434146976177459312/gif_torneios_068B442.png?ex=69089674&is=690744f4&hm=e28e5146a72f1fd98052ee04e84b812b1c9ffb2c42cb8c9186920f10a8544c46&",  # Placeholder, update with actual rapid banner
            "classic": "https://cdn.discordapp.com/attachments/1393788085455687802/1434146986218487899/gif_torneios_Copy_845CA62.png?ex=69089676&is=690744f6&hm=669035f2b768eca96eac0869f7b8ba02e143c87f3da2f127a2b844b9b2880532&"  # Placeholder, update with actual classic banner
        }
        banner_embed.set_image(url=banner_urls.get(mode, banner_urls["bullet"]))

        try:
            # A operação potencialmente lenta e que pode dar erro - buscar os top 8 jogadores
            top_players = await database.get_top_players_by_mode(mode, 8)

            if not top_players:
                embed = discord.Embed(
                    title=f"🏆 | Ranking {mode.capitalize()}",
                    description=f"Não há jogadores suficientes no ranking de {mode} ainda.",
                    color = 0xCD0000
                )
                await interaction.edit_original_response(embeds=[banner_embed, embed], view=self)
                return

            # Criar lista de embeds: banner + um embed por jogador
            embeds = [banner_embed]

            for i, player in enumerate(top_players, 1):
                discord_id = player.get('discord_id')
                discord_username = player.get('discord_username', 'Desconhecido')
                try:
                    print(f"[RANK] Jogador idx={i} discord_id={discord_id} discord_username={discord_username}")
                except Exception:
                    pass

                if discord_id:
                    discord_mention = f"<@{discord_id}>"
                else:
                    discord_mention = discord_username

                if i <= 3:
                    medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
                    title = f"{medal} #{i} - {discord_username}"
                    # Set color based on position
                    if i == 1:
                        color = 0xFFD700  # Gold
                    elif i == 2:
                        color = 0xC0C0C0  # Silver
                    else:  # i == 3
                        color = 0xCD7F32  # Bronze
                else:
                    title = f"#{i} - {discord_username}"
                    color = 0xCD0000

                player_embed = discord.Embed(
                    title=title,
                    color=color
                )

                # Obter avatar do usuário
                if discord_id:
                    try:
                        member = interaction.guild.get_member(int(discord_id)) if interaction.guild else None
                        if member:
                            avatar_url = member.display_avatar.url
                        else:
                            # Fallback para buscar o usuário global
                            user = await self.bot.fetch_user(int(discord_id))
                            if user:
                                avatar_url = user.display_avatar.url
                            else:
                                avatar_url = None

                        if avatar_url:
                            player_embed.set_thumbnail(url=avatar_url)
                    except Exception as e:
                        print(f"Erro ao obter avatar do usuário {discord_id}: {e}")

                # Criar descrição com todas as informações em uma linha
                lichess_username = player.get('lichess_username', 'Sem Lichess')
                lichess_link = f"https://lichess.org/@/{lichess_username}" if lichess_username != 'Sem Lichess' else 'Sem Lichess'

                description = f"👤 ➜ Usuário: {discord_mention}\n🔗 ➜ Lichess: [{lichess_username}]({lichess_link})\n⭐ ➜ Rating: **{player['rating']}**\n🎯 ➜ Modo: {mode.capitalize()}"

                # # Adicionar emblemas
                # if discord_id:
                #     achievements = await database.get_player_achievements(discord_id)
                #     if achievements:
                #         badge_emojis = {
                #             'default': '<:verified:1446673529989890168>',
                #             'tournament_winner': '<:champion:1446676107029123163>'
                #         }
                #         badges_str = " ".join([f"{badge_emojis.get(ach['achievement_type'], '🏅')}" for ach in achievements])
                #         description += f"\n\n{badges_str}"

                player_embed.description = description

                embeds.append(player_embed)

            # Criar embed separado para o footer
            footer_embed = discord.Embed(
                color = 0xCD0000
            )
            footer_embed.set_footer(text="💡 O rating é atualizado a cada partida | Use os botões para ver outros modos.")
            embeds.append(footer_embed)

            await interaction.edit_original_response(embeds=embeds, view=self)

        except Exception as e:
            # Se QUALQUER COISA der errado no bloco try acima, este código será executado.
            print(f"ERRO CRÍTICO AO BUSCAR RANKING ({mode}): {type(e).__name__} - {e}")

            error_embed = discord.Embed(
                title="❌ Erro ao Carregar Ranking",
                description="Ocorreu um erro inesperado ao buscar os dados do ranking. Tente novamente mais tarde.",
                color=discord.Color.red()
            )
            # Mostra uma mensagem de erro no próprio menu
            await interaction.edit_original_response(embed=error_embed, view=None)
            # Para a view para evitar mais cliques com erro
            self.stop()

    # --- Botões de Modo de Jogo (linha 0) ---
    @discord.ui.button(label="Bullet", style=discord.ButtonStyle.grey, custom_id="rank_bullet", row=0)
    async def bullet_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        try:
            await self.show_ranking(interaction, "bullet")
        except discord.errors.InteractionResponded:
            await self.handle_expired_interaction(interaction, "bullet")

    @discord.ui.button(label="Blitz", style=discord.ButtonStyle.grey, custom_id="rank_blitz", row=0)
    async def blitz_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        try:
            await self.show_ranking(interaction, "blitz")
        except discord.errors.InteractionResponded:
            await self.handle_expired_interaction(interaction, "blitz")

    @discord.ui.button(label="Rapid", style=discord.ButtonStyle.grey, custom_id="rank_rapid", row=0)
    async def rapid_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        try:
            await self.show_ranking(interaction, "rapid")
        except discord.errors.InteractionResponded:
            await self.handle_expired_interaction(interaction, "rapid")

    @discord.ui.button(label="Clássico", style=discord.ButtonStyle.grey, custom_id="rank_classic", row=0)
    async def classic_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        try:
            await self.show_ranking(interaction, "classic")
        except discord.errors.InteractionResponded:
            await self.handle_expired_interaction(interaction, "classic")

    # --- Botões de Navegação (linha 1) ---
    @discord.ui.button(label="Voltar", style=discord.ButtonStyle.blurple, custom_id="rank_back", row=1)
    async def back_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        try:
            await self.show_menu(interaction)
        except discord.errors.InteractionResponded:
            await self.handle_expired_interaction(interaction)

    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.danger, custom_id="rank_close", row=1)
    async def close_button(self, interaction: discord.Interaction, button: Button):
        try:
            await interaction.response.defer()
            await interaction.delete_original_response()
            self.stop()
        except discord.errors.InteractionResponded:
            # Se a interação já foi respondida, apenas para a view
            self.stop()
        except discord.Forbidden:
            await interaction.followup.send("❌ Não consigo fechar o menu porque não tenho a permissão de 'Gerenciar Mensagens'.", ephemeral=True)
        except Exception as e:
            print(f"Erro ao tentar fechar a mensagem de rankings: {e}")
            await interaction.followup.send("❌ Ocorreu um erro inesperado ao tentar fechar o menu.", ephemeral=True)


class Rankings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fixed_ranking_view = None
        self.fixed_ranking_message_id = None
        self.fixed_ranking_channel_id = None
        self.fixed_ranking_recreated = False

    @app_commands.command(name="rankings", description="Mostra os rankings do servidor.")
    async def show_rankings(self, interaction: discord.Interaction):
        """Mostra os rankings do servidor."""
        view = RankingView(interaction.user.id, self.bot)

        embed = discord.Embed(
            title="Legion Chess | Rankings",
            description="Selecione um modo para ver seu Ranking.",
            color = 0xCD0000
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="set_fixed_ranking", description="Define o canal para o ranking fixo (apenas administradores).")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_fixed_ranking(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Define o canal onde o ranking fixo será exibido."""
        # Cria a mensagem fixa
        view = RankingView(None, self.bot, is_fixed=True, fixed_mode='default')  # Sem autor específico para ranking fixo

        embed = discord.Embed(
            title="Legion Chess | Rankings",
            description="Selecione um modo para ver seu Ranking.",
            color = 0xCD0000
        )

        message = await channel.send(embed=embed, view=view)

        # Salva as configurações no banco de dados
        # Backwards compatibility: save as generic fixed ranking (mode=None)
        await database.set_ranking_channel('default', str(channel.id), str(message.id))

        await interaction.response.send_message(f"✅ Ranking fixo configurado no canal {channel.mention}!\n\n⚠️ **Nota:** Após restart do bot, use `/recreate_fixed_ranking` para restaurar a funcionalidade dos botões.", ephemeral=True)

    @app_commands.command(name="recreate_fixed_ranking", description="Recria a funcionalidade do ranking fixo após restart do bot (apenas administradores).")
    @app_commands.checks.has_permissions(administrator=True)
    async def recreate_fixed_ranking(self, interaction: discord.Interaction):
        """Recria a funcionalidade do ranking fixo após restart do bot."""
        await self.auto_recreate_fixed_ranking()
        await interaction.response.send_message("✅ Tentativa de recriação do ranking fixo concluída. Verifique se os botões estão funcionando.", ephemeral=True)

    async def auto_recreate_fixed_ranking(self):
        """Recria automaticamente o ranking fixo quando o bot inicia."""
        if self.fixed_ranking_recreated:
            return  # Já foi recriado nesta sessão

        try:
            # Recreate all per-mode ranking messages
            channels = await database.get_all_ranking_channels()
            if not channels:
                print("Nenhum canal de ranking configurado.")
                return

            for rc in channels:
                mode = rc.get('mode')
                channel_id = rc.get('channel_id')
                message_id = rc.get('message_id')
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if not channel:
                        print(f"Canal do ranking ({mode}) não encontrado: {channel_id}")
                        continue
                    if not message_id:
                        print(f"Nenhuma mensagem salva para ranking {mode} no canal {channel.name}")
                        continue
                    try:
                        message = await channel.fetch_message(int(message_id))
                        view = RankingView(None, self.bot, is_fixed=True, fixed_mode=mode)
                        await message.edit(view=view)
                        print(f"✅ Ranking fixo ({mode}) recriado automaticamente no canal {channel.name}")
                    except discord.NotFound:
                        print(f"Mensagem do ranking fixo ({mode}) não encontrada - será necessário configurar novamente.")
                    except Exception as e:
                        print(f"Erro ao recriar ranking fixo ({mode}) automaticamente: {e}")
                except Exception as e:
                    print(f"Erro ao processar canal de ranking ({mode}): {e}")

            self.fixed_ranking_recreated = True

        except Exception as e:
            print(f"Erro ao buscar configurações do ranking fixo: {e}")

    async def update_fixed_ranking(self):
        """Atualiza o ranking fixo após mudanças nos ratings."""
        try:
            # Atualiza todos os canais de ranking configurados por modo
            channels = await database.get_all_ranking_channels()
            if not channels:
                return

            for rc in channels:
                mode = rc.get('mode')
                channel_id = rc.get('channel_id')
                message_id = rc.get('message_id')

                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if not channel:
                        continue
                    if not message_id:
                        continue

                    try:
                        message = await channel.fetch_message(int(message_id))
                        # Rebuild embeds for this mode and edit the message
                        embeds = await self.build_embeds_for_mode(mode, channel)
                        view = RankingView(None, self.bot, is_fixed=True, fixed_mode=mode)
                        await message.edit(embeds=embeds, view=view)
                        print(f"✅ Ranking fixo ({mode}) atualizado após mudança de rating")
                    except discord.NotFound:
                        print(f"Mensagem do ranking fixo ({mode}) não encontrada para atualização")
                    except Exception as e:
                        print(f"Erro ao atualizar ranking fixo ({mode}): {e}")
                except Exception as e:
                    print(f"Erro ao processar atualização de ranking ({mode}): {e}")

        except Exception as e:
            print(f"Erro ao buscar configurações para atualização do ranking fixo: {e}")

    async def build_embeds_for_mode(self, mode: str, channel: discord.abc.GuildChannel):
        """Constrói e retorna uma lista de embeds para o ranking do modo informado."""
        try:
            banner_embed = discord.Embed(color=0xCD0000)
            banner_urls = {
                "bullet": "https://media.discordapp.net/attachments/1393788085455687802/1434146966593474641/gif_torneios_Copy_Copy_C936744.png",
                "blitz": "https://cdn.discordapp.com/attachments/1393788085455687802/1434147563023499405/Novo_projeto_14_626ADA3.png",
                "rapid": "https://cdn.discordapp.com/attachments/1393788085455687802/1434146976177459312/gif_torneios_068B442.png",
                "classic": "https://cdn.discordapp.com/attachments/1393788085455687802/1434146986218487899/gif_torneios_Copy_845CA62.png"
            }
            banner_embed.set_image(url=banner_urls.get(mode, banner_urls["bullet"]))

            top_players = await database.get_top_players_by_mode(mode, 8)
            if not top_players:
                embed = discord.Embed(
                    title=f"🏆 | Ranking {mode.capitalize()}",
                    description=f"Não há jogadores suficientes no ranking de {mode} ainda.",
                    color=0xCD0000
                )
                return [banner_embed, embed]

            embeds = [banner_embed]
            for i, player in enumerate(top_players, 1):
                discord_id = player.get('discord_id')
                discord_username = player.get('discord_username', 'Desconhecido')

                if discord_id:
                    discord_mention = f"<@{discord_id}>"
                else:
                    discord_mention = discord_username

                if i <= 3:
                    medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
                    title = f"{medal} #{i} - {discord_username}"
                    color = 0xFFD700 if i == 1 else 0xC0C0C0 if i == 2 else 0xCD7F32
                else:
                    title = f"#{i} - {discord_username}"
                    color = 0xCD0000

                player_embed = discord.Embed(title=title, color=color)

                # Tentar anexar thumbnail com avatar se o usuário estiver no guild
                avatar_url = None
                try:
                    guild = channel.guild if hasattr(channel, 'guild') else None
                    if guild and discord_id:
                        member = guild.get_member(int(discord_id))
                        if member:
                            avatar_url = member.display_avatar.url
                        else:
                            user = await self.bot.fetch_user(int(discord_id))
                            avatar_url = user.display_avatar.url if user else None
                except Exception:
                    avatar_url = None

                if avatar_url:
                    player_embed.set_thumbnail(url=avatar_url)

                lichess_username = player.get('lichess_username', 'Sem Lichess')
                lichess_link = f"https://lichess.org/@/{lichess_username}" if lichess_username != 'Sem Lichess' else 'Sem Lichess'

                description = f"👤 ➜ Usuário: {discord_mention}\n🔗 ➜ Lichess: [{lichess_username}]({lichess_link})\n⭐ ➜ Rating: **{player['rating']}**\n🎯 ➜ Modo: {mode.capitalize()}"
                # # Adicionar emblemas
                # if discord_id:
                #     achievements = await database.get_player_achievements(discord_id)
                #     if achievements:
                #         badge_emojis = {
                #             'default': '<:verified:1446673529989890168>',
                #             'tournament_winner': '<:champion:1446676107029123163>'
                #         }
                #         badges_str = " ".join([f"{badge_emojis.get(ach['achievement_type'], '🏅')}" for ach in achievements])
                #         description += f"\n\n{badges_str}"

                player_embed.description = description
                embeds.append(player_embed)

            footer_embed = discord.Embed(color=0xCD0000)
            footer_embed.set_footer(text="💡 O rating é atualizado a cada partida | Use os botões para ver outros modos.")
            embeds.append(footer_embed)

            return embeds
        except Exception as e:
            print(f"Erro ao construir embeds para ranking {mode}: {e}")
            return [discord.Embed(title="Erro ao gerar ranking", description=str(e), color=discord.Color.red())]

    @app_commands.command(name="set_ranking_channel", description="Configura o canal e mensagem fixa para um modo de ranking (admin).")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(mode=[
        app_commands.Choice(name="Bullet", value="bullet"),
        app_commands.Choice(name="Blitz", value="blitz"),
        app_commands.Choice(name="Rapid", value="rapid"),
        app_commands.Choice(name="Classic", value="classic")
    ])
    async def set_ranking_channel(self, interaction: discord.Interaction, mode: app_commands.Choice[str], channel: discord.TextChannel):
        """Cria a mensagem fixa de ranking para um modo específico e salva as configurações."""
        await interaction.response.defer(ephemeral=True)
        try:
            embeds = await self.build_embeds_for_mode(mode.value, channel)
            view = RankingView(None, self.bot, is_fixed=True, fixed_mode=mode.value)
            message = await channel.send(embeds=embeds, view=view)
            await database.set_ranking_channel(mode.value, str(channel.id), str(message.id))
            await interaction.followup.send(f"✅ Ranking fixo para **{mode.name}** configurado no canal {channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro ao configurar ranking fixo: {e}", ephemeral=True)

    @app_commands.command(name="remove_ranking_channel", description="Remove a configuração de canal de ranking para um modo (admin).")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(mode=[
        app_commands.Choice(name="Bullet", value="bullet"),
        app_commands.Choice(name="Blitz", value="blitz"),
        app_commands.Choice(name="Rapid", value="rapid"),
        app_commands.Choice(name="Classic", value="classic")
    ])
    async def remove_ranking_channel(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        try:
            await database.remove_ranking_channel(mode.value)
            await interaction.followup.send(f"✅ Removido canal de ranking para **{mode.name}**.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro ao remover configuração: {e}", ephemeral=True)

    @set_fixed_ranking.error
    async def set_fixed_ranking_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Você precisa ser administrador para usar este comando.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Ocorreu um erro ao configurar o ranking fixo.", ephemeral=True)


async def setup(bot: commands.Bot):
    rankings_cog = Rankings(bot)
    await bot.add_cog(rankings_cog)
    print("[LOG] Rankings cog carregado com 3 comandos.")

    # Aguardar o bot estar pronto e recriar ranking fixo automaticamente
    @bot.event
    async def on_ready():
        print("Bot pronto! Tentando recriar ranking fixo...")
        await rankings_cog.auto_recreate_fixed_ranking()
