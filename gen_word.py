# -*- coding: utf-8 -*-
"""手搓最小但合法的 .docx（OAOXML zip），小白版内容。"""
import zipfile, os, datetime

OUT = r"C:\Users\J\WorkBuddy\2026-08-17-08-58-49\淘宝视觉合规巡检系统_使用与设计说明.docx"

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

def make_runs(text):
    parts = str(text).split("**")
    return "".join(runs_xml(p, bold=(i % 2 == 1)) for i, p in enumerate(parts) if p != "")

def runs_xml(text, bold=False, mono=False, color=None, sz=None):
    rpr = ['<w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s" w:cs="Times New Roman"/>' % (
        ("Consolas" if mono else "Calibri"), ("Consolas" if mono else "Calibri"),
        "宋体")]
    if bold:
        rpr.append("<w:b/>")
    if color:
        rpr.append('<w:color w:val="%s"/>' % color)
    if sz:
        rpr.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (sz, sz))
    return "<w:r><w:rPr>%s</w:rPr><w:t xml:space=\"preserve\">%s</w:t></w:r>" % ("".join(rpr), esc(text))

def para(text="", style=None, space_after=80, mono=False):
    ppr = []
    if style:
        ppr.append('<w:pStyle w:val="%s"/>' % style)
    ppr.append('<w:spacing w:after="%d"/>' % space_after)
    ppr_xml = "<w:pPr>%s</w:pPr>" % "".join(ppr)
    if text == "":
        return "<w:p>%s</w:p>" % ppr_xml
    body = runs_xml(text, mono=True, sz=18) if mono else make_runs(text)
    return "<w:p>%s%s</w:p>" % (ppr_xml, body)

def table(rows, header=True, widths=None):
    ncol = max(len(r) for r in rows)
    if widths is None:
        widths = [int(9000 / ncol)] * ncol
    grid = "".join('<w:gridCol w:w="%d"/>' % w for w in widths)
    borders = ('<w:tblBorders>'
               '<w:top w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
               '<w:left w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
               '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
               '<w:right w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
               '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
               '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
               '</w:tblBorders>')
    tblpr = ('<w:tblPr><w:tblW w:w="0" w:type="auto"/>%s'
             '<w:tblLook w:val="04A0"/></w:tblPr>' % borders)
    out = ['<w:tbl>%s<w:tblGrid>%s</w:tblGrid>' % (tblpr, grid)]
    for ri, row in enumerate(rows):
        cells = []
        for ci in range(ncol):
            txt = row[ci] if ci < len(row) else ""
            is_h = header and ri == 0
            shd = '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % ("2E5496" if is_h else "FFFFFF")
            tcpr = '<w:tcPr><w:tcW w:w="%d" w:type="dxa"/>%s</w:tcPr>' % (widths[ci], shd)
            runs = make_runs(txt)
            cell = '<w:tc>%s<w:p><w:pPr><w:spacing w:after="20"/></w:pPr>%s</w:p></w:tc>' % (tcpr, runs)
            cells.append(cell)
        out.append('<w:tr>%s</w:tr>' % "".join(cells))
    out.append("</w:tbl>")
    out.append('<w:p><w:pPr><w:spacing w:after="60"/></w:pPr></w:p>')
    return "".join(out)

# ---------------- 小白版内容 ----------------
B = []
B.append(para("淘宝店铺“拍照查违规”系统 — 新手傻瓜手册", style="Title"))
B.append(para("看一遍就会用 · 数据截至 2026-08-21 · 配套还有一份给技术同事的《使用与设计说明》"))

B.append(para("一、这到底是啥（先搞懂）", style="Heading1"))
B.append(para("**一句话**：它是一个帮你“检查代理商淘宝店有没有乱来”的内部网站。", space_after=60))
B.append(para("**打个比方**：你品牌方，外面很多店在卖你的货。你担心它们偷偷**改价格、写违规词、乱贴牛皮癣广告、或者直接偷用你官方旗舰店的主图**。这个系统帮你把【官方旗舰店的标准图】和【代理商的店】放一起，自动“拍照”对比，告诉你代理商哪里不对。", space_after=60))
B.append(para("**它能帮你省的事**：不用你一个个店手动翻图；查出的问题自动留记录；最后还能出一张统计表拿去汇报。"))

B.append(para("二、怎么用（照着点就行）", style="Heading1"))

B.append(para("第 1 步：第一次打开，登记一下", style="Heading2"))
B.append(para("网页会弹出一个小窗，让你填“**姓名 + 部门**”，填完点确定就进去了。**不用注册账号**，谁用谁填。"))

B.append(para("第 2 步：让淘宝“记住”你（很重要，做一次就行）", style="Heading2"))
B.append(para("网页上有个【**扫码登录淘宝 / 天猫**】按钮，点一下，会弹出一个浏览器窗口，用你的**手机淘宝扫个码**登录。", space_after=60))
B.append(para("扫这一次之后，系统就能自己去抓淘宝的商品图了，你不用再填那些看不懂的“Cookie”。要是哪天提示过期了，重新扫一次就行。"))

B.append(para("第 3 步：把“标准照片”录进去", style="Heading2"))
B.append(para("点左边菜单的【**视觉标准库**】，把官方旗舰店的标准图传上去，起个名字。这就像给系统存一份“**正确答案样本**”，以后拿它去比别的店。"))

B.append(para("第 4 步：开始检查一个商品", style="Heading2"))
B.append(para("点左边菜单的【**违规看板**】，在页面上方照着填：", space_after=40))
B.append(para("① **代理商链接**：那个卖你货的淘宝店的网址；", space_after=20))
B.append(para("② **官旗标准链接**：你官方旗舰店对应商品的网址；", space_after=20))
B.append(para("③（可选）要比哪类图：全部 / 只比主图 / 只比 SKU 图 / 只比详情图；", space_after=20))
B.append(para("④ 点【**开始单链接巡检**】，剩下的交给系统去抓图、比对。", space_after=60))
B.append(para("**一次查很多个？** 点【下载对照表模板】，在 Excel 里把一堆链接填好，再点【选择 Excel 上传】，系统会一个个帮你查。"))

B.append(para("第 5 步：看结果（哪里不对一目了然）", style="Heading2"))
B.append(para("查完后，在【违规看板】里按店铺分组显示。点开任意一条，会**左右并排**显示：左边官旗图、右边代理图，哪里不一样、缺了哪张图，都会标出来。", space_after=60))
B.append(para("如果开了 AI 比对，还会用大白话说：“**这里像违规 / 没问题 / 拿不准，原因是……**”。要是没开 AI，页面会注明“这是机器粗略比对，仅供参考”，别全信。"))

B.append(para("第 6 步：处理查出的问题（四步走）", style="Heading2"))
B.append(table([
    ["状态", "啥意思 / 你该干嘛"],
    ["待处理", "刚查出来，还没动作"],
    ["已通知", "你勾选问题 → 点【批量通知选中】→ 发给代理让他们改"],
    ["已修改", "代理改完了，状态变这个"],
    ["已核销", "你验收通过，上传整改后的截图证明，这事闭环啦"],
], widths=[2000, 7000]))
B.append(para("点错了？有【**撤回**】按钮可以退回去重来。", space_after=40))

B.append(para("第 7 步：看统计、交差", style="Heading2"))
B.append(para("点左边【**数据报表**】，能看到查了多少、改了多少、合格率、最近趋势，还能点【**导出 CSV**】下载下来拿去汇报。"))

B.append(para("三、它背后是怎么干活的（浅显版，看不懂可跳过）", style="Heading1"))
B.append(para("**说人话**：系统用一个“浏览器机器人”跑到那两个链接，把图一张张拍下来存好；然后交给 **AI 看这两张图一不一样、代理有没有违规**（比如改价、写违规词、偷图）。万一 AI 暂时用不了，它就退回“机器粗略看两张图像不像”来顶一下，并且会老实标注“仅供参考”。", space_after=60))
B.append(para("所有查过的记录都存在一个本地小数据库里，**刷新网页、关掉重开都不丢**。"))

B.append(para("四、接下来还要改啥（大白话版）", style="Heading1"))
B.append(table([
    ["排行", "还要改啥", "现在是啥情况"],
    ["①", "机器人拍照还不准", "拍图有时会拍错类别、漏拍，这是目前最大的毛病，得先治好它，不然比对的结论不可信"],
    ["②", "AI 还在测试阶段", "AI 已换成更聪明的“多模态大模型”，但还没联网真跑过；需要填上密钥、联网验证一下才能放心用"],
    ["③", "网站偶尔会卡", "人多了或崩了没人自动重启；要加个“挂了自动起来”的机制，保证大家随时能打开"],
    ["④", "按钮不好用", "功能都有，但点起来别扭；要重新排版，让常用操作顺手"],
    ["⑤", "放到公网上", "现在只能在你自己电脑上打开，要部署到服务器，让团队都能访问"],
    ["⑥", "对付淘宝反爬", "淘宝偶尔出验证码 / 限流，现在靠“过期重扫”顶着；如果频繁再上代理等手段"],
], widths=[900, 2700, 5400]))
B.append(para("总进度约 **84%**，但上面①②③④ 这四项还没达标，是当前重点。"))

B.append(para("附：技术同事怎么把环境跑起来（小白可跳过）", style="Heading1"))
B.append(para("cd app\npython -m venv venv && source venv/bin/activate   # Windows 用 venv\\Scripts\\activate\npip install -r requirements.txt\nplaywright install chromium\n# 在网站「淘宝/天猫登录」面板扫码登录（生成登录记录文件）\n# 在项目根目录 .env 里写 VISION_API_KEY=sk-xxx（想用 AI 比对才需要）\npython -m uvicorn app:app --host 0.0.0.0 --port 8000\n# 浏览器打开 http://127.0.0.1:8000 ，地址后面加 /docs 能看到所有接口", mono=True))
B.append(para("代码目前只存在原作者的电脑本地（3 次提交，还没推到远程仓库），接手同事需要从原作者那拷贝整个文件夹，或等原作者上传后再下载。", space_after=40))

body = "".join(B)

document_xml = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<w:body>' + body +
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
    '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
    '</w:sectPr></w:body></w:document>'
)

content_types = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
    '</Types>'
)

rels = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
    '</Relationships>'
)

doc_rels = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '</Relationships>'
)

styles_xml = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:docDefaults><w:rPrDefault><w:rPr>'
    '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="宋体" w:cs="Times New Roman"/>'
    '<w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:rPrDefault>'
    '<w:pPrDefault><w:pPr><w:spacing w:after="80" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
    '</w:docDefaults>'
    '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:spacing w:before="0" w:after="160"/></w:pPr>'
    '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="黑体"/><w:b/><w:sz w:val="40"/><w:szCs w:val="40"/><w:color w:val="1F3864"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>'
    '<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="0"/></w:pPr>'
    '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="黑体"/><w:b/><w:sz w:val="30"/><w:szCs w:val="30"/><w:color w:val="2E5496"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>'
    '<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="60"/><w:outlineLvl w:val="1"/></w:pPr>'
    '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="黑体"/><w:b/><w:sz w:val="24"/><w:szCs w:val="24"/><w:color w:val="2E5496"/></w:rPr></w:style>'
    '</w:styles>'
)

now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
core_xml = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    '<dc:title>淘宝店铺拍照查违规系统 — 新手傻瓜手册</dc:title>'
    '<dc:creator>WorkBuddy</dc:creator>'
    '<cp:lastModifiedBy>WorkBuddy</cp:lastModifiedBy>'
    '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
    '<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
    '</cp:coreProperties>' % (now, now)
)

app_xml = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
    '<Application>WorkBuddy</Application><Company>淘宝视觉合规巡检</Company></Properties>'
)

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml", content_types)
    z.writestr("_rels/.rels", rels)
    z.writestr("word/document.xml", document_xml)
    z.writestr("word/_rels/document.xml.rels", doc_rels)
    z.writestr("word/styles.xml", styles_xml)
    z.writestr("docProps/core.xml", core_xml)
    z.writestr("docProps/app.xml", app_xml)

print("WROTE", OUT, os.path.getsize(OUT), "bytes")
