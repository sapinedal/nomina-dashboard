"""Guardas sobre la configuracion de nginx (unittest hermetico, sin deps).

Los tres fallos que tumbaron el sitio el 25 de agosto fueron regresiones de
configuracion que ningun test miraba: server_tokens en el contexto principal,
un listen 443 apuntando a certificados inexistentes y puertos del host en
conflicto con Traefik. A eso se suma la herencia de add_header, que descartaba
en silencio las cabeceras DEF-0004 en todo el frontend estatico.

Estas pruebas leen los .conf como texto: no necesitan nginx ni las deps de la
app, y corren en el CI hermetico actual.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NGINX = REPO / "nginx"

SECURITY_INCLUDE = "include /etc/nginx/security-headers.conf;"

# Perfil por defecto (TLS lo termina el proxy) y perfil standalone.
PROFILES = ["nginx.conf", "nginx.standalone-tls.conf"]

DEF_0004_HEADERS = [
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
    "Content-Security-Policy",
]


def strip_comments(text):
    return "\n".join(re.sub(r"#.*$", "", line) for line in text.splitlines())


def iter_location_blocks(text):
    """Devuelve (cabecera, cuerpo_directo) de cada bloque `location`.

    `cuerpo_directo` excluye los bloques anidados, que nginx trata como un
    nivel aparte a efectos de herencia.
    """
    text = strip_comments(text)
    for match in re.finditer(r"location\s+([^{]+?)\s*\{", text):
        start = match.end()
        depth, i = 1, start
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        yield match.group(1).strip(), text[start : i - 1]


class TestSecurityHeadersInclude(unittest.TestCase):
    def test_el_fragmento_compartido_existe_y_trae_las_cabeceras(self):
        frag = NGINX / "security-headers.conf"
        self.assertTrue(frag.is_file(), f"falta {frag}")
        body = frag.read_text(encoding="utf-8")
        for header in DEF_0004_HEADERS:
            self.assertIn(
                header, body, f"security-headers.conf no declara {header}"
            )

    def test_todo_location_con_add_header_incluye_las_de_seguridad(self):
        """nginx no acumula add_header entre niveles.

        Un location que declara add_header propio descarta TODAS las del
        server. Si anade cabeceras de cache sin reincluir las de seguridad,
        esas respuestas salen sin CSP ni X-Frame-Options.
        """
        for profile in PROFILES:
            path = NGINX / profile
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for header, body in iter_location_blocks(text):
                if "add_header" not in body:
                    continue
                with self.subTest(profile=profile, location=header):
                    self.assertIn(
                        SECURITY_INCLUDE,
                        body,
                        f"{profile}: el location '{header}' declara add_header "
                        f"propio y no reincluye security-headers.conf, asi que "
                        f"pierde las cabeceras DEF-0004",
                    )


class TestArranqueDeNginx(unittest.TestCase):
    def test_server_tokens_nunca_en_el_contexto_principal(self):
        """Regresion del PR 18: nginx aborta con [emerg] si esta fuera de http."""
        for profile in PROFILES:
            path = NGINX / profile
            if not path.is_file():
                continue
            main_context = strip_comments(
                path.read_text(encoding="utf-8")
            ).split("http", 1)[0]
            with self.subTest(profile=profile):
                self.assertNotIn(
                    "server_tokens",
                    main_context,
                    f"{profile}: server_tokens solo se admite en http, server "
                    f"o location; en el contexto principal impide el arranque",
                )

    def test_el_dockerfile_copia_todo_include_de_etc_nginx(self):
        """Un include que no esta en la imagen impide el arranque."""
        dockerfile = (NGINX / "Dockerfile").read_text(encoding="utf-8")
        conf = strip_comments((NGINX / "nginx.conf").read_text(encoding="utf-8"))
        for included in re.findall(r"include\s+(/etc/nginx/\S+?);", conf):
            name = included.rsplit("/", 1)[-1]
            if name == "mime.types":  # lo trae la imagen base
                continue
            with self.subTest(include=included):
                self.assertIn(
                    name,
                    dockerfile,
                    f"nginx.conf incluye {included} pero el Dockerfile no lo "
                    f"copia: el contenedor no arrancara",
                )


class TestPerfilDetrasDeProxy(unittest.TestCase):
    """nginx.conf es el perfil que se construye en la imagen (ver Dockerfile).

    Detras de Traefik no debe terminar TLS ni reclamar el 443: eso fue el
    fallo del PR 14.
    """

    def setUp(self):
        self.conf = strip_comments(
            (NGINX / "nginx.conf").read_text(encoding="utf-8")
        )

    def test_no_termina_tls(self):
        self.assertNotIn("listen 443", self.conf)
        self.assertNotIn("ssl_certificate", self.conf)

    def test_no_referencia_certificados(self):
        self.assertNotIn("/etc/nginx/certs", self.conf)


if __name__ == "__main__":
    unittest.main()
