# =============================================================================
# visualizacao/mapa.py
# Visualização interativa de rotas do DronePharm usando Folium
#
# Gera mapas HTML interativos com:
# - Marcadores por tipo de ponto (depósito, entrega urgente, normal)
# - Rotas coloridas por voo
# - Popups detalhados com métricas de cada pedido
# - Painel lateral com resumo da missão
# - Círculos de alcance do drone
# - Legenda visual completa
# =============================================================================

from __future__ import annotations
import os
import json
import webbrowser
from datetime import datetime
from typing import List, Optional

from models.pedido import Pedido, Coordenada
from models.rota import Rota
from models.drone import Drone
from config.settings import (
    DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE, DEPOSITO_NOME,
    PRIORIDADE_URGENTE, PRIORIDADE_NORMAL, PRIORIDADE_REABASTEC,
)

# -----------------------------------------------------------------------------
# Paleta de cores para rotas (até 10 voos simultâneos)
# -----------------------------------------------------------------------------
CORES_ROTAS = [
    "#2196F3",   # Azul     — Voo 1
    "#4CAF50",   # Verde    — Voo 2
    "#FF9800",   # Laranja  — Voo 3
    "#9C27B0",   # Roxo     — Voo 4
    "#F44336",   # Vermelho — Voo 5
    "#00BCD4",   # Ciano    — Voo 6
    "#FF5722",   # Deep Orange — Voo 7
    "#8BC34A",   # Verde claro — Voo 8
    "#E91E63",   # Rosa     — Voo 9
    "#607D8B",   # Azul acinzentado — Voo 10
]

COR_DEPOSITO = "#1A237E"   # Azul escuro
COR_URGENTE  = "#B71C1C"   # Vermelho escuro
COR_NORMAL   = "#1565C0"   # Azul médio
COR_REABAST  = "#2E7D32"   # Verde escuro
COR_ROTA_BG  = "#ECEFF1"   # Fundo de card


# =============================================================================
# CLASSE PRINCIPAL
# =============================================================================

class VisualizadorRotas:
    """
    Gera um mapa HTML interativo com as rotas calculadas pelo DronePharm.

    Uso
    ---
    viz = VisualizadorRotas(drone, pedidos, rotas)
    viz.gerar_mapa("output/mapa_rotas.html")
    viz.abrir_no_navegador()
    """

    def __init__(
        self,
        drone:   Drone,
        pedidos: List[Pedido],
        rotas:   List[Rota],
        titulo:  str = "DronePharm — Rotas de Entrega",
    ):
        self.drone   = drone
        self.pedidos = pedidos
        self.rotas   = rotas
        self.titulo  = titulo
        self._mapa   = None
        self._caminho_html: Optional[str] = None

    # ------------------------------------------------------------------
    def gerar_mapa(self, caminho: str = "output/mapa_rotas.html") -> str:
        """
        Gera o mapa completo e salva como arquivo HTML.

        Parâmetros
        ----------
        caminho : caminho de saída do arquivo HTML

        Retorna
        -------
        str : caminho absoluto do arquivo gerado
        """
        try:
            import folium
            from folium.plugins import MiniMap, MousePosition, MeasureControl
        except ImportError:
            raise ImportError(
                "Folium não instalado. Execute:\n"
                "  pip install folium\n"
                "no terminal do PyCharm (Alt+F12)."
            )

        os.makedirs(os.path.dirname(caminho) if os.path.dirname(caminho) else ".", exist_ok=True)

        # ── Centro do mapa: média das coordenadas de todos os pontos ──────────
        todas_lats = [DEPOSITO_LATITUDE]  + [p.coordenada.latitude  for p in self.pedidos]
        todas_lons = [DEPOSITO_LONGITUDE] + [p.coordenada.longitude for p in self.pedidos]
        centro     = [sum(todas_lats) / len(todas_lats), sum(todas_lons) / len(todas_lons)]

        # ── Inicializa o mapa base ────────────────────────────────────────────
        self._mapa = folium.Map(
            location=centro,
            zoom_start=13,
            tiles="OpenStreetMap",
            control_scale=True,
        )

        # ── Adiciona plugins ──────────────────────────────────────────────────
        MiniMap(toggle_display=True).add_to(self._mapa)
        MousePosition(
            position="bottomleft",
            separator=" | lon: ",
            prefix="lat: ",
        ).add_to(self._mapa)
        MeasureControl(primary_length_unit="kilometers").add_to(self._mapa)

        # ── Grupos de camadas (podem ser ligados/desligados no mapa) ──────────
        grupo_deposito = folium.FeatureGroup(name="Depósito", show=True)
        grupo_pedidos  = folium.FeatureGroup(name="Pontos de Entrega", show=True)
        grupo_rotas    = folium.FeatureGroup(name="Rotas", show=True)
        grupo_alcance  = folium.FeatureGroup(name="Alcance do Drone", show=False)

        # ── Renderiza cada camada ─────────────────────────────────────────────
        self._adicionar_deposito(grupo_deposito)
        self._adicionar_circulo_alcance(grupo_alcance)
        self._adicionar_pedidos(grupo_pedidos)
        self._adicionar_rotas(grupo_rotas)

        # ── Adiciona camadas ao mapa ──────────────────────────────────────────
        grupo_deposito.add_to(self._mapa)
        grupo_pedidos.add_to(self._mapa)
        grupo_rotas.add_to(self._mapa)
        grupo_alcance.add_to(self._mapa)

        # ── Controle de camadas ───────────────────────────────────────────────
        folium.LayerControl(collapsed=False).add_to(self._mapa)

        # ── Painel HTML de resumo ─────────────────────────────────────────────
        self._adicionar_painel_resumo()

        # ── Legenda ───────────────────────────────────────────────────────────
        self._adicionar_legenda()

        # ── Salva ─────────────────────────────────────────────────────────────
        self._mapa.save(caminho)
        self._caminho_html = os.path.abspath(caminho)
        print(f"\n✓ Mapa salvo em: {self._caminho_html}")
        return self._caminho_html

    # ------------------------------------------------------------------
    def abrir_no_navegador(self):
        """Abre o mapa gerado no navegador padrão do sistema."""
        if not self._caminho_html or not os.path.exists(self._caminho_html):
            raise RuntimeError("Gere o mapa primeiro com gerar_mapa().")
        webbrowser.open(f"file://{self._caminho_html}")
        print("Mapa aberto no navegador.")

    # ==========================================================================
    # MÉTODOS INTERNOS DE RENDERIZAÇÃO
    # ==========================================================================

    def _adicionar_deposito(self, grupo):
        """Adiciona o marcador do depósito central."""
        import folium

        # Ícone personalizado do depósito
        icone = folium.DivIcon(
            html=f"""
            <div style="
                background:{COR_DEPOSITO};
                border:3px solid white;
                border-radius:50%;
                width:22px; height:22px;
                display:flex; align-items:center; justify-content:center;
                box-shadow:0 2px 6px rgba(0,0,0,0.5);
                font-size:12px;
            ">🏭</div>""",
            icon_size=(28, 28),
            icon_anchor=(14, 14),
        )

        popup_html = f"""
        <div style="font-family:Arial;min-width:220px">
            <h4 style="color:{COR_DEPOSITO};margin:0 0 8px 0">🏭 Depósito Central</h4>
            <b>{DEPOSITO_NOME}</b><br>
            <hr style="margin:6px 0">
            <table style="width:100%;font-size:12px">
                <tr><td>Latitude</td><td><b>{DEPOSITO_LATITUDE:.6f}</b></td></tr>
                <tr><td>Longitude</td><td><b>{DEPOSITO_LONGITUDE:.6f}</b></td></tr>
                <tr><td>Drone</td><td><b>{self.drone.nome}</b></td></tr>
                <tr><td>Capacidade</td><td><b>{self.drone.capacidade_max_kg} kg</b></td></tr>
                <tr><td>Autonomia</td><td><b>{self.drone.autonomia_max_km} km</b></td></tr>
                <tr><td>Voos planejados</td><td><b>{len(self.rotas)}</b></td></tr>
            </table>
        </div>
        """

        folium.Marker(
            location=[DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE],
            popup=folium.Popup(popup_html, max_width=260),
            tooltip=f"🏭 {DEPOSITO_NOME}",
            icon=icone,
        ).add_to(grupo)

    # ------------------------------------------------------------------
    def _adicionar_circulo_alcance(self, grupo):
        """Adiciona círculo indicando o alcance máximo do drone."""
        import folium

        folium.Circle(
            location=[DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE],
            radius=self.drone.autonomia_max_km * 1000 / 2,   # raio = metade da autonomia (ida+volta)
            color=COR_DEPOSITO,
            fill=True,
            fill_color=COR_DEPOSITO,
            fill_opacity=0.05,
            weight=1.5,
            dash_array="8",
            tooltip=f"Alcance operacional: {self.drone.autonomia_max_km/2:.1f} km (raio)",
        ).add_to(grupo)

    # ------------------------------------------------------------------
    def _adicionar_pedidos(self, grupo):
        """Adiciona marcadores para cada pedido com popup detalhado."""
        import folium

        for pedido in self.pedidos:
            cor, emoji, label_prio = self._estilo_prioridade(pedido.prioridade)

            # Identifica em qual voo este pedido está
            voo_num = self._voo_do_pedido(pedido.id)
            cor_voo = CORES_ROTAS[(voo_num - 1) % len(CORES_ROTAS)] if voo_num else "#777"

            # Ícone colorido por prioridade
            icone = folium.DivIcon(
                html=f"""
                <div style="
                    background:{cor};
                    border:2.5px solid {cor_voo};
                    border-radius:50%;
                    width:20px; height:20px;
                    display:flex; align-items:center; justify-content:center;
                    box-shadow:0 2px 5px rgba(0,0,0,0.4);
                    font-size:11px;
                    color:white;
                    font-weight:bold;
                ">{pedido.id}</div>""",
                icon_size=(24, 24),
                icon_anchor=(12, 12),
            )

            tempo_restante = pedido.tempo_restante_s
            tr_min = int(tempo_restante / 60) if tempo_restante != float("inf") else "—"

            popup_html = f"""
            <div style="font-family:Arial;min-width:240px">
                <h4 style="color:{cor};margin:0 0 6px 0">{emoji} Pedido #{pedido.id}</h4>
                <b>{pedido.descricao or 'Medicamento'}</b><br>
                <hr style="margin:6px 0">
                <table style="width:100%;font-size:12px;border-collapse:collapse">
                    <tr style="background:#f5f5f5">
                        <td style="padding:3px 6px">Prioridade</td>
                        <td style="padding:3px 6px"><b style="color:{cor}">{label_prio}</b></td>
                    </tr>
                    <tr>
                        <td style="padding:3px 6px">Peso</td>
                        <td style="padding:3px 6px"><b>{pedido.peso_kg} kg</b></td>
                    </tr>
                    <tr style="background:#f5f5f5">
                        <td style="padding:3px 6px">Tempo restante</td>
                        <td style="padding:3px 6px"><b>{tr_min} min</b></td>
                    </tr>
                    <tr>
                        <td style="padding:3px 6px">Voo designado</td>
                        <td style="padding:3px 6px">
                            <b style="color:{cor_voo}">Voo {voo_num or '—'}</b>
                        </td>
                    </tr>
                    <tr style="background:#f5f5f5">
                        <td style="padding:3px 6px">Coordenadas</td>
                        <td style="padding:3px 6px;font-size:10px">
                            {pedido.coordenada.latitude:.6f},<br>
                            {pedido.coordenada.longitude:.6f}
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:3px 6px">Status</td>
                        <td style="padding:3px 6px">
                            {'<b style="color:green">✓ Entregue</b>' if pedido.entregue
                             else '<b style="color:orange">⏳ Pendente</b>'}
                        </td>
                    </tr>
                </table>
            </div>
            """

            folium.Marker(
                location=[pedido.coordenada.latitude, pedido.coordenada.longitude],
                popup=folium.Popup(popup_html, max_width=280),
                tooltip=f"{emoji} Pedido #{pedido.id} — {label_prio} | {pedido.peso_kg}kg",
                icon=icone,
            ).add_to(grupo)

    # ------------------------------------------------------------------
    def _adicionar_rotas(self, grupo):
        """Desenha as linhas de rota para cada voo com animação e popup."""
        import folium

        deposito = [DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE]

        for i, rota in enumerate(self.rotas):
            if rota.esta_vazia():
                continue

            cor  = CORES_ROTAS[i % len(CORES_ROTAS)]
            seq  = [p.id for p in rota.pedidos]

            # Monta a sequência de coordenadas: depósito → entregas → depósito
            coords = [deposito]
            for pedido in rota.pedidos:
                coords.append([pedido.coordenada.latitude, pedido.coordenada.longitude])
            coords.append(deposito)

            # Linha principal da rota
            folium.PolyLine(
                locations=coords,
                color=cor,
                weight=3.5,
                opacity=0.85,
                tooltip=f"Voo {i+1}: {' → '.join(str(s) for s in seq)}",
                popup=folium.Popup(
                    self._popup_rota(i + 1, rota, cor),
                    max_width=300
                ),
            ).add_to(grupo)

            # Setas de direção ao longo da rota
            self._adicionar_setas(coords, cor, grupo, i + 1)

            # Marcador de número do voo no centroide da rota
            centroide = self._centroide(coords)
            folium.DivIcon(
                html=f"""
                <div style="
                    background:{cor};color:white;
                    border-radius:12px;padding:2px 8px;
                    font-size:11px;font-weight:bold;font-family:Arial;
                    box-shadow:0 1px 4px rgba(0,0,0,0.4);
                    white-space:nowrap;
                ">✈ Voo {i+1}</div>""",
                icon_size=(60, 22),
                icon_anchor=(30, 11),
            )
            folium.Marker(
                location=centroide,
                icon=folium.DivIcon(
                    html=f"""
                    <div style="
                        background:{cor};color:white;
                        border-radius:10px;padding:2px 7px;
                        font-size:11px;font-weight:bold;font-family:Arial;
                        box-shadow:0 1px 4px rgba(0,0,0,0.35);
                        white-space:nowrap;border:1.5px solid white;
                    ">✈ Voo {i+1}</div>""",
                    icon_size=(65, 22),
                    icon_anchor=(32, 11),
                ),
                tooltip=f"Voo {i+1} — {rota.distancia_total_km:.2f} km | {rota.tempo_total_min:.1f} min",
            ).add_to(grupo)

    # ------------------------------------------------------------------
    def _adicionar_setas(self, coords, cor, grupo, voo_num):
        """Adiciona setas indicando o sentido do voo ao longo da rota."""
        import folium

        for j in range(len(coords) - 1):
            p1, p2 = coords[j], coords[j + 1]
            meio   = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2]

            # Calcula ângulo de rotação para a seta
            import math
            dlat = p2[0] - p1[0]
            dlon = p2[1] - p1[1]
            angulo = math.degrees(math.atan2(dlon, dlat))

            folium.Marker(
                location=meio,
                icon=folium.DivIcon(
                    html=f"""
                    <div style="
                        transform:rotate({angulo}deg);
                        font-size:16px;
                        color:{cor};
                        text-shadow:0 0 3px white;
                        line-height:1;
                    ">➤</div>""",
                    icon_size=(20, 20),
                    icon_anchor=(10, 10),
                ),
                tooltip=f"Voo {voo_num} — sentido de voo",
            ).add_to(grupo)

    # ------------------------------------------------------------------
    def _adicionar_painel_resumo(self):
        """Adiciona painel HTML flutuante com resumo da missão."""
        import folium
        dist_total   = sum(r.distancia_total_km for r in self.rotas)
        tempo_total  = sum(r.tempo_total_s      for r in self.rotas) / 60
        energia_total= sum(r.energia_wh         for r in self.rotas)
        n_urgentes   = sum(1 for p in self.pedidos if p.prioridade == PRIORIDADE_URGENTE)
        gerado_em    = datetime.now().strftime("%d/%m/%Y %H:%M")

        linhas_voos = ""
        for i, rota in enumerate(self.rotas):
            cor = CORES_ROTAS[i % len(CORES_ROTAS)]
            ids = ", ".join(str(p.id) for p in rota.pedidos)
            linhas_voos += f"""
            <tr>
                <td style="padding:3px 8px">
                    <span style="color:{cor};font-weight:bold">■ Voo {i+1}</span>
                </td>
                <td style="padding:3px 8px">{ids}</td>
                <td style="padding:3px 8px">{rota.distancia_total_km:.2f} km</td>
                <td style="padding:3px 8px">{rota.tempo_total_min:.0f} min</td>
                <td style="padding:3px 8px">{rota.carga_total_kg:.2f} kg</td>
            </tr>"""

        painel_html = f"""
        <div id="painel-resumo" style="
            position:fixed;top:80px;right:12px;z-index:1000;
            background:white;border-radius:10px;
            box-shadow:0 4px 20px rgba(0,0,0,0.2);
            font-family:Arial;font-size:12px;
            min-width:340px;max-width:400px;
            border-top:4px solid {COR_DEPOSITO};
        ">
            <!-- Cabeçalho -->
            <div style="
                background:{COR_DEPOSITO};color:white;
                padding:10px 14px;border-radius:6px 6px 0 0;
                display:flex;justify-content:space-between;align-items:center;
            ">
                <div>
                    <div style="font-size:14px;font-weight:bold">✈ DronePharm</div>
                    <div style="font-size:10px;opacity:0.85">{self.titulo}</div>
                </div>
                <div style="font-size:10px;opacity:0.75">{gerado_em}</div>
            </div>

            <!-- Métricas gerais -->
            <div style="padding:10px 14px;display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid #eee">
                {self._card_metrica("📦", "Pedidos", len(self.pedidos))}
                {self._card_metrica("✈️", "Voos", len(self.rotas))}
                {self._card_metrica("🚨", "Urgentes", n_urgentes, COR_URGENTE if n_urgentes else None)}
                {self._card_metrica("📏", "Distância", f"{dist_total:.1f} km")}
                {self._card_metrica("⏱", "Tempo", f"{tempo_total:.0f} min")}
                {self._card_metrica("⚡", "Energia", f"{energia_total:.0f} Wh")}
            </div>

            <!-- Drone -->
            <div style="padding:8px 14px;background:#F5F7FA;border-bottom:1px solid #eee;font-size:11px">
                🤖 <b>{self.drone.nome}</b> &nbsp;|&nbsp;
                Capacidade: {self.drone.capacidade_max_kg} kg &nbsp;|&nbsp;
                Autonomia: {self.drone.autonomia_max_km} km &nbsp;|&nbsp;
                Bateria: {self.drone.bateria_pct*100:.0f}%
            </div>

            <!-- Tabela de voos -->
            <div style="padding:8px 14px">
                <div style="font-weight:bold;margin-bottom:6px;color:{COR_DEPOSITO}">
                    Detalhes por Voo
                </div>
                <table style="width:100%;border-collapse:collapse;font-size:11px">
                    <thead>
                        <tr style="background:#EEF2FF;color:{COR_DEPOSITO}">
                            <th style="padding:4px 8px;text-align:left">Voo</th>
                            <th style="padding:4px 8px;text-align:left">Pedidos</th>
                            <th style="padding:4px 8px;text-align:left">Dist.</th>
                            <th style="padding:4px 8px;text-align:left">Tempo</th>
                            <th style="padding:4px 8px;text-align:left">Carga</th>
                        </tr>
                    </thead>
                    <tbody>
                        {linhas_voos}
                    </tbody>
                </table>
            </div>

            <!-- Botão minimizar -->
            <div style="
                padding:6px 14px;text-align:right;
                border-top:1px solid #eee;
            ">
                <button onclick="
                    var corpo=document.getElementById('painel-corpo');
                    corpo.style.display=corpo.style.display==='none'?'block':'none';
                    this.textContent=corpo.style.display==='none'?'▼ Expandir':'▲ Minimizar';
                " style="
                    font-size:10px;padding:2px 8px;cursor:pointer;
                    background:{COR_DEPOSITO};color:white;border:none;
                    border-radius:4px;
                ">▲ Minimizar</button>
            </div>
        </div>
        """
        self._mapa.get_root().html.add_child(
            folium.Element(painel_html)
        )

    # ------------------------------------------------------------------
    def _adicionar_legenda(self):
        """Adiciona legenda de prioridades ao mapa."""
        import folium
        legenda_html = f"""
        <div style="
            position:fixed;bottom:40px;left:12px;z-index:1000;
            background:white;border-radius:8px;
            box-shadow:0 2px 10px rgba(0,0,0,0.2);
            font-family:Arial;font-size:11px;padding:10px 14px;
            border-left:4px solid {COR_DEPOSITO};
        ">
            <div style="font-weight:bold;color:{COR_DEPOSITO};margin-bottom:6px">
                Legenda — Prioridade
            </div>
            <div style="display:flex;flex-direction:column;gap:4px">
                <div>
                    <span style="
                        background:{COR_URGENTE};color:white;
                        border-radius:50%;padding:1px 6px;font-weight:bold;font-size:10px
                    ">1</span>
                    &nbsp; <b>Urgente</b> — UTI / Emergência
                </div>
                <div>
                    <span style="
                        background:{COR_NORMAL};color:white;
                        border-radius:50%;padding:1px 6px;font-weight:bold;font-size:10px
                    ">2</span>
                    &nbsp; <b>Normal</b> — Entrega padrão
                </div>
                <div>
                    <span style="
                        background:{COR_REABAST};color:white;
                        border-radius:50%;padding:1px 6px;font-weight:bold;font-size:10px
                    ">3</span>
                    &nbsp; <b>Reabastecimento</b> — Estoque
                </div>
                <hr style="margin:4px 0;border-color:#eee">
                <div>
                    <span style="color:{COR_DEPOSITO};font-size:14px">🏭</span>
                    &nbsp; Depósito / Farmácia-polo
                </div>
            </div>
        </div>
        """
        self._mapa.get_root().html.add_child(
            folium.Element(legenda_html)
        )

    # ==========================================================================
    # HELPERS
    # ==========================================================================

    def _popup_rota(self, num: int, rota: Rota, cor: str) -> str:
        ids = " → ".join(str(p.id) for p in rota.pedidos)
        return f"""
        <div style="font-family:Arial;min-width:240px">
            <h4 style="color:{cor};margin:0 0 8px 0">✈ Voo {num}</h4>
            <table style="width:100%;font-size:12px;border-collapse:collapse">
                <tr style="background:#f5f5f5">
                    <td style="padding:4px 8px">Sequência</td>
                    <td style="padding:4px 8px"><b>Depósito → {ids} → Depósito</b></td>
                </tr>
                <tr>
                    <td style="padding:4px 8px">Entregas</td>
                    <td style="padding:4px 8px"><b>{rota.num_entregas}</b></td>
                </tr>
                <tr style="background:#f5f5f5">
                    <td style="padding:4px 8px">Distância</td>
                    <td style="padding:4px 8px"><b>{rota.distancia_total_km:.2f} km</b></td>
                </tr>
                <tr>
                    <td style="padding:4px 8px">Tempo estimado</td>
                    <td style="padding:4px 8px"><b>{rota.tempo_total_min:.1f} min</b></td>
                </tr>
                <tr style="background:#f5f5f5">
                    <td style="padding:4px 8px">Carga total</td>
                    <td style="padding:4px 8px"><b>{rota.carga_total_kg:.2f} kg</b></td>
                </tr>
                <tr>
                    <td style="padding:4px 8px">Energia est.</td>
                    <td style="padding:4px 8px"><b>{rota.energia_wh:.1f} Wh</b></td>
                </tr>
                <tr style="background:#f5f5f5">
                    <td style="padding:4px 8px">Viável</td>
                    <td style="padding:4px 8px">
                        {'<b style="color:green">✓ Sim</b>' if rota.viavel
                         else '<b style="color:red">✗ Não</b>'}
                    </td>
                </tr>
            </table>
        </div>
        """

    def _card_metrica(self, emoji: str, label: str, valor, cor: str = None) -> str:
        cor_val = f"color:{cor};" if cor else ""
        return f"""
        <div style="
            background:#F0F4FF;border-radius:6px;
            padding:5px 8px;text-align:center;min-width:70px;flex:1;
        ">
            <div style="font-size:14px">{emoji}</div>
            <div style="font-size:15px;font-weight:bold;{cor_val}">{valor}</div>
            <div style="font-size:9px;color:#666">{label}</div>
        </div>"""

    def _estilo_prioridade(self, prioridade: int):
        if prioridade == PRIORIDADE_URGENTE:
            return COR_URGENTE, "🚨", "Urgente (P1)"
        elif prioridade == PRIORIDADE_NORMAL:
            return COR_NORMAL, "📦", "Normal (P2)"
        else:
            return COR_REABAST, "🔄", "Reabastecimento (P3)"

    def _voo_do_pedido(self, pedido_id: int) -> Optional[int]:
        for i, rota in enumerate(self.rotas):
            if any(p.id == pedido_id for p in rota.pedidos):
                return i + 1
        return None

    def _centroide(self, coords: list) -> list:
        lats = [c[0] for c in coords]
        lons = [c[1] for c in coords]
        return [sum(lats) / len(lats), sum(lons) / len(lons)]


# =============================================================================
# FUNÇÃO DE CONVENIÊNCIA — uso rápido em main.py
# =============================================================================

def gerar_mapa_rotas(
    drone:   Drone,
    pedidos: List[Pedido],
    rotas:   List[Rota],
    caminho: str  = "output/mapa_rotas.html",
    abrir:   bool = True,
) -> str:
    """
    Atalho para gerar e (opcionalmente) abrir o mapa em uma única chamada.

    Parâmetros
    ----------
    drone   : drone utilizado na missão
    pedidos : lista de pedidos carregados
    rotas   : rotas otimizadas pelo algoritmo
    caminho : destino do arquivo HTML
    abrir   : se True, abre automaticamente no navegador padrão

    Retorna
    -------
    str : caminho absoluto do arquivo gerado

    Exemplo
    -------
    from visualizacao.mapa import gerar_mapa_rotas
    gerar_mapa_rotas(drone, pedidos, rotas, abrir=True)
    """
    viz = VisualizadorRotas(drone, pedidos, rotas)
    caminho_abs = viz.gerar_mapa(caminho)
    if abrir:
        viz.abrir_no_navegador()
    return caminho_abs