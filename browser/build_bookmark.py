"""将现有脚本打包为本地书签安装页；无外部依赖。"""

from html import escape
from pathlib import Path
from urllib.parse import quote


def build():
    folder = Path(__file__).resolve().parent
    source = (folder / "get_token.js").read_text(encoding="utf-8")
    bookmark = "javascript:" + quote("void(function(){\n" + source + "\n}())", safe="")
    (folder / "token_bookmark.txt").write_text(bookmark, encoding="utf-8")
    page = """<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><title>安装上汽 Token 书签</title>
<style>body{max-width:760px;margin:50px auto;padding:20px;font:17px/1.8 system-ui;color:#172033}
a.bookmark{display:inline-block;padding:12px 24px;background:#2563eb;color:white;border-radius:8px;text-decoration:none}
textarea{width:100%;height:100px;box-sizing:border-box}small{color:#526076}</style>
<h1>上汽 Token 获取书签</h1>
<p>不需要在 Console 粘贴代码。请将下面的蓝色链接<strong>拖到浏览器书签栏</strong>保存。</p>
<p><a class="bookmark" href="BOOKMARK">获取上汽 Token</a></p>
<ol><li>按 Ctrl+Shift+B 显示书签栏，将上面的链接拖进去。</li>
<li>打开 <a href="https://saic-px.saicmotor.com/" target="_blank" rel="noopener">上汽平台</a>并完成登录。</li>
<li>在平台页面点击书签栏中的“获取上汽 Token”。</li>
<li>等待验证成功，点击弹出面板的“复制 Token”，然后粘贴到桌面工作台。</li></ol>
<p>不要在本安装页直接点击蓝色链接执行；它应在已登录的平台页面运行。</p>
<details><summary>拖动无效：手动创建书签</summary>
<p>新建任意书签，右键编辑，把“网址 / URL”替换为下面的整段内容，保存。
如浏览器编辑器移除了开头的 <code>javascript:</code>，请手动补上。</p>
<textarea readonly aria-label="书签完整地址" onclick="this.select()">BOOKMARK_TEXT</textarea></details>
<p><small>书签复用本项目 get_token.js，仅向上汽平台发送登录验证请求。凭证在平台页面内处理。</small></p>
</html>"""
    page = page.replace("BOOKMARK_TEXT", escape(bookmark)).replace("BOOKMARK", escape(bookmark, quote=True))
    target = folder / "token_bookmark.html"
    target.write_text(page, encoding="utf-8")
    print(target)


if __name__ == "__main__":
    build()
