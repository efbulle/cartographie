"""Plusieurs types de cartes dynamiques.

Toutes les coordonnées sont en EPSG 3857 Pseudo-Mercator.
"""

from pathlib import Path
from pandas import Series, DataFrame
from geopandas import read_file
from bokeh.models import (
    GeoJSONDataSource,
    HoverTool,
    DataTable,
    TableColumn,
    TextInput,
    CustomJS,
    NumberFormatter,
    Div,
    Toggle,
    CDSView,
    IndexFilter,
    Box,
)
from bokeh.plotting import figure
from bokeh.tile_providers import get_provider
from bokeh.layouts import row, column
from bokeh.palettes import brewer
from bokeh.resources import CDN
import bokeh.io as io
from bokeh.models import Div, Box

data_path = Path(__file__).parent / "data"
regex_pk_dec = r"(?P<add1>\d+|\D)(?P<op>[+-])(?P<add2>\d+)"
pk_c = {
    "D": 0,
    "E": 1,
    "F": 2,
    "G": 3,
    "H": 4,
}  # pk particuliers pour lignes 983000 et 984000 (Invalides à Austerlitz)


def pk_dec(pk: Series) -> Series:
    """Renvoie une série de pk entiers à partir des pk littéraux."""
    dec = pk.str.extract(regex_pk_dec).astype({"add2": float})
    dec["add1"] = dec["add1"].replace(pk_c).astype(float)
    dec2 = (dec["add1"] * 1000).add(dec["add2"].where(dec["op"] == "+", -dec["add2"]))
    try:  # à changer avec le nouveau type Int64 quand il sera stabilisé
        return dec2.astype(int)
    except ValueError:
        return dec2.astype(float)


class Fond_de_carte:
    """Classe de base pour les cartes dynamiques, ne pas utiliser directement.

    Arguments:
        titre: titre à afficher sur la carte et comme onglet
        tile: si vrai (par défaut) ajout des tiles de CartoDB Tile Service
        fig_height: hauteur du widget carte (la largeur s'ajuste en conséquence)
    """

    titre_ref = "Carte"
    save_path = Path(__file__).parent / "résultats"

    def __init__(self, titre: str = None, tile: bool = True, fig_height: int = 760) -> None:
        self.titre = titre if titre is not None else self.titre_ref
        self.p = figure(
            height=fig_height,
            sizing_mode="stretch_both",
            tools="pan,hover,tap,wheel_zoom,reset,save",
            tooltips=self.tooltips,
            active_scroll="wheel_zoom",
            title=self.titre,
            x_axis_type="mercator",
            y_axis_type="mercator",
            match_aspect=True,
            aspect_scale=1,
        )
        self.tile = tile
        if tile:
            self.p.add_tile(get_provider("CARTODBPOSITRON"))

    @property
    def tooltips(self) -> list[tuple[str, str]]:
        pass

    @property
    def text_aide(self) -> str:
        return "<b>Mode d'emploi</b>"

    def init_layout(self) -> None:
        self.aide = Div(
            text=self.text_aide,
            style={"overflow-y": "scroll", "height": "200px"},
        )
        self.texte_questions = Div(text="""<a href="https://github.com/efbulle/cartographie">Code source</a>""")

    def cstr_layout(self) -> Box:
        return self.p

    def affiche(self, save=False) -> None:
        self.init_layout()
        layout = self.cstr_layout()
        io.show(layout)
        if save:
            io.save(layout, self.save_path / f"{self.titre}.html", resources=CDN, title=self.titre)


class Carte_tronçons(Fond_de_carte):
    """Carte de tronçons de lignes.

    Arguments:
        tronçons: GeoDataFrame, table des tronçons

    Attributs:
        tron: table des tronçons avec habillage
        tron_idx_name: le nom de l'index des tronçons transformé en colonne dans `tron`
    """

    titre_ref = "carte_tronçons"
    titre_tron = "Tronçons"
    # coordonnées arbitraires de la carte pour créer des objets de la légende
    x_legende, y_legende = [277409, 277409], [6248780, 6248780]
    tab_width = 500

    def __init__(self, tronçons: DataFrame, **kwargs) -> None:
        self.tron = tronçons
        self.tron["line_width"] = self.line_width
        self.tron["line_color"] = self.line_color
        self.tron.reset_index(inplace=True)
        self.tron_idx_name = self.tron.columns[0]
        self.cols = self.tron.columns.drop(["geometry", "line_width", "line_color"], errors="ignore")
        super().__init__(**kwargs)

    @property
    def cols_tron(self) -> list[TableColumn]:
        return [TableColumn(field=c, title=c) for c in self.cols]

    @property
    def line_width(self) -> Series:
        """Épaisseur de l'affichage des tronçons.

        Doit renvoyer une série alignable avec l'argument tronçons
        et peut y faire référence via self.tron.
        """
        return 2

    @property
    def line_color(self) -> Series:
        """Couleur de l'affichage des tronçons.

        Doit renvoyer une série alignable avec l'argument tronçons
        et peut y faire référence via self.tron.
        """
        return "blue"

    @property
    def tooltips(self) -> list[tuple[str, str]]:
        return [(c, f"@{c}") for c in self.cols]

    @property
    def text_aide(self) -> str:
        return """<b>Mode d'emploi</b>
        <p>La sélection d'une ou plusieurs lignes est possible directement sur la carte (shift + clic) ou dans la table (shift/ctrl + clic).</p>
        <p>On peut aussi sélectionner une ligne en indiquant son numéro de ligne et de rang dans l'entrée texte située en haut à droite. 
        Le bouton "Affiche les extrémités" permet de rendre visibles ou non les extrémités des lignes sélectionnées.</p>
        <p>En cas de problème, utiliser l'outil reset sur la droite de la carte.</p>
        """

    def ajoute_table_tron(self) -> None:
        view = CDSView(source=self.source_lines, filters=[self.filter])
        self.table_tron = DataTable(
            source=self.source_lines,
            view=view,
            columns=self.cols_tron,
            autosize_mode="none",
            sizing_mode="stretch_height",
            width=self.tab_width,
            height=200,
        )

    def ajoute_toggle_extrémités(self) -> None:
        size = 4
        fill_color = "DarkSlateGray"
        self.g = (
            self.tron.set_index(self.tron_idx_name)
            .geometry.boundary.dropna()
            .explode()
            .droplevel(1)
            .rename("geometry")
            .reset_index()
            .reset_index()
        )
        idx_g = self.g.columns[0]  # colonne qui contient le numéro de ligne
        self.src_extr = GeoJSONDataSource(geojson=self.g.to_json())
        self.filter_extr = IndexFilter(list(range(self.g.shape[0])))
        self.index_extrémités_par_tron = (
            self.tron.reset_index()  # numéro de ligne dans la colonne idx_g
            .merge(self.g, on=self.tron_idx_name)  # inner join donc tous les tronçons non localisés n'y sont pas
            .groupby(f"{idx_g}_x")
            .apply(lambda s: list(s[f"{idx_g}_y"]))
            .to_dict()
        )
        view = CDSView(source=self.src_extr, filters=[self.filter_extr])
        self.extr_renderer = self.p.circle(
            x="x",
            y="y",
            size=size,
            fill_color=fill_color,
            line_color=fill_color,
            source=self.src_extr,
            visible=False,
            view=view,
        )
        self.toggle_extr = Toggle(label="Affiche les extrémités", button_type="success", width=100)
        self.toggle_extr.js_link("active", self.extr_renderer, "visible")

    def ajoute_lignes(self) -> None:
        self.p.multi_line(
            xs="xs",
            ys="ys",
            line_color="line_color",
            line_width="line_width",
            source=self.source_lines,
            name="tronçons",
        )

    @property
    def callback_selected(self) -> CustomJS:
        return CustomJS(
            args=dict(
                src_lines=self.source_lines,
                src_extr=self.src_extr,
                filter=self.filter,
                filter_extr=self.filter_extr,
                index_extr_dict=self.index_extrémités_par_tron,
            ),
            code="""var sel = src_lines.selected.indices;
            if (sel.length == 0) {
                sel = [...Array(src_lines.length).keys()];
                var sel2 = [...Array(src_extr.length).keys()];
            } else {
                var sel2 = sel.flatMap(el => index_extr_dict[el]);
            }
            filter.indices = sel;
            filter_extr.indices = sel2;
            src_lines.change.emit();
            src_extr.change.emit();
            """,
        )

    def ajoute_input_num(self, title: str = None, groupby: str = None, max_width=80) -> None:
        """Sélection du tronçon par une colonne de la table."""
        if groupby is None:
            groupby = self.tron_idx_name
        if title is None:
            title = self.tron_idx_name
        index_par_tron = DataFrame(self.tron).groupby(groupby).apply(lambda s: list(s.index)).to_dict()
        self.input_num = TextInput(value="", title=title, max_width=max_width)
        callback_text = CustomJS(
            args=dict(
                text=self.input_num,
                src_lines=self.source_lines,
                index_par_tron=index_par_tron,
            ),
            code="""if (text.value in index_par_tron) {
                src_lines.selected.indices = index_par_tron[text.value]
                src_lines.change.emit();
                }
                """,
        )
        self.input_num.js_on_change("value", callback_text)

    def ajoute_légende(self) -> None:
        pass

    @property
    def titre_tron_div(self) -> Div:
        return Div(text=f"<b>{self.titre_tron}</b>")

    def init_layout(self) -> None:
        super().init_layout()
        geojson = self.tron.to_json().replace("null", '{"type":"Point","coordinates":[]}')
        self.source_lines = GeoJSONDataSource(geojson=geojson)
        self.filter = IndexFilter(list(range(self.tron.shape[0])))
        self.ajoute_lignes()
        self.ajoute_toggle_extrémités()
        self.source_lines.selected.js_on_change("indices", self.callback_selected)
        self.ajoute_table_tron()
        self.ajoute_input_num()
        self.hover_tool = self.p.select(type=HoverTool)
        self.hover_tool.names = ["tronçons"]
        self.ajoute_légende()
        self.première_ligne = row(self.input_num, self.toggle_extr)

    def cstr_layout(self) -> Box:
        return row(
            self.p,
            column(
                self.première_ligne,
                self.titre_tron_div,
                self.table_tron,
                self.texte_questions,
                self.aide,
            ),
        )


class Carte_Lignes(Carte_tronçons):
    """Carte des lignes avec régime d'exploitation.

    Données issues de
    https://data.sncf.com/explore/dataset/regime-dexploitation-des-lignes/information/
    """

    titre_ref = "Carte des lignes"
    c1, c2, c3, *_ = brewer["Purples"][8]
    groupes = [
        ("Voie double ou banalisée", ["Double voie", "Voie banalisée"], c1, 2),
        (
            "Voie unique",
            [
                "Voie unique",
                "Voie unique à trafic restreint (consigne de ligne)",
                "Voie unique à signalisation simplifiée",
                "Régime particulier de voie unique autre que trafic restreint",
            ],
            c2,
            1,
        ),
        ("Autres", ["_Autre", "Régime en navette"], c3, 1),
    ]
    lgv = ("DodgerBlue", 3)

    def __init__(self, **kwargs) -> None:
        t = (
            read_file("zip://" + str(data_path / "regime-dexploitation-des-lignes.zip"), encoding="utf-8")
            .assign(
                lig_rg=lambda s: s["code_ligne"].str.pad(6, fillchar="0")
                + "-"
                + s["rg_troncon"].astype(int).astype(str),
                pk_dec_d=lambda s: pk_dec(s["pkd"]),
                pk_dec_f=lambda s: pk_dec(s["pkf"]),
                long_km=lambda s: (s["pk_dec_f"] - s["pk_dec_d"]).div(1000),
            )
            .to_crs(3857)
        ).rename({"exploitati": "exploitation"}, axis=1)[
            ["lig_rg", "lib_ligne", "exploitation", "pkd", "pkf", "long_km", "geometry"]
        ]
        self.habillages = self.groupes
        super().__init__(tronçons=t, **kwargs)

    @property
    def line_color(self) -> Series:
        d = {}
        for _, régimes, lc, _ in self.groupes:
            for r in régimes:
                d[r] = lc
        self.tron.loc[:, "line_color"] = self.tron["exploitation"].map(d)
        self.tron.loc[lambda s: s["lib_ligne"].str.contains("LGV"), "line_color"] = self.lgv[0]
        return self.tron["line_color"]

    @property
    def line_width(self) -> Series:
        d = {}
        for _, régimes, _, lw in self.groupes:
            for r in régimes:
                d[r] = lw
        self.tron.loc[:, "line_width"] = self.tron["exploitation"].map(d)
        self.tron.loc[lambda s: s["lib_ligne"].str.contains("LGV"), "line_width"] = self.lgv[1]
        return self.tron["line_width"]

    @property
    def cols_tron(self) -> None:
        return [
            TableColumn(field="lig_rg", title="lig_rg", width=55),
            TableColumn(field="long_km", title="long_km", width=40, formatter=NumberFormatter(format="0.0")),
            TableColumn(field="pkd", title="pkd", width=60),
            TableColumn(field="pkf", title="pkf", width=60),
            TableColumn(field="lib_ligne", title="ligne", width=200),
            TableColumn(field="exploitation", title="exploitation", width=100),
        ]

    @property
    def callback_selected(self) -> CustomJS:
        return CustomJS(
            args=dict(
                src_lines=self.source_lines,
                src_extr=self.src_extr,
                filter=self.filter,
                filter_extr=self.filter_extr,
                index_extr_dict=self.index_extrémités_par_tron,
            ),
            code="""var sel = src_lines.selected.indices;
            if (sel.length == 0) {
                var sel2 = [...Array(src_extr.length).keys()];
            } else {
                var sel2 = sel.flatMap(el => index_extr_dict[el]);
            }
            filter_extr.indices = sel2;
            src_lines.change.emit();
            src_extr.change.emit();
            """,
        )

    def ajoute_input_num(self) -> None:
        super().ajoute_input_num(groupby="lig_rg", title="ligne_rg (ex: 001000-1)", max_width=150)

    def ajoute_légende(self) -> None:
        # contournement en l'absence de legend_field
        # Add support for legend_field with geo data
        # https://github.com/bokeh/bokeh/issues/9398
        self.p.line(
            x=self.x_legende,
            y=self.y_legende,
            line_color=self.lgv[0],
            line_width=self.lgv[1],
            legend_label="LGV",
            visible=False,
        )
        for lib, _, lc, lw in self.groupes:
            self.p.line(
                x=self.x_legende,
                y=self.y_legende,
                line_color=lc,
                line_width=lw,
                legend_label=lib,
                visible=False,
            )
