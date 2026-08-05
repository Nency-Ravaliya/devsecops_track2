import zipfile
from xml.sax.saxutils import escape

SLIDES = [
    {
        'title': 'Cloud Platform & DevSecOps Security Assessment',
        'body': [
            'Track 2 — Multi-Cloud Government Programme',
            '45-minute panel presentation',
        ],
    },
    {
        'title': 'Executive Summary',
        'body': [
            'The assessment identified 30 findings across AWS, Azure, and GCP with significant remediation urgency.',
            '13 Critical findings: public exposure, committed credentials, wildcard IAM.',
            '13 High findings: open management ports, disabled encryption, missing detection.',
            '4 Medium findings: key rotation, supply-chain immutability, audit coverage gaps.',
        ],
    },
    {
        'title': 'Key Findings and Impact',
        'body': [
            'Public storage buckets without access controls or encryption.',
            'Public and unencrypted databases exposed to the internet.',
            'Wildcard CI permissions and overly broad IAM access.',
            'Inconsistent logging and no centralised detection.',
        ],
    },
    {
        'title': 'Prioritisation Approach',
        'body': [
            'Sequence by blast radius × exploitability × remediation cost.',
            'P0 — Stop exposure immediately: public data, credentials, wildcard IAM.',
            'P1 — Urgent control repair: open ports, missing encryption, missing detection.',
            'P2 — Near-term hardening: rotation, governance, audit coverage.',
        ],
    },
    {
        'title': 'Connected Security Story',
        'body': [
            'Identity: OIDC federation, scoped CI roles, no static credentials.',
            'Network: private application and data tiers, centralised firewall and edge controls.',
            'Data: encryption at rest and in transit, native KMS with central policy governance.',
            'Detection: centralised SIEM and alerting across all clouds.',
        ],
    },
    {
        'title': 'Architecture High-Level View',
        'body': [
            'Development zone with GitLab and CI/CD scanning.',
            'Central identity boundary using Entra ID and federated cloud access.',
            'Public edge tier for TLS termination and WAF protection.',
            'Hub/shared services in AWS, Azure, and GCP with private data tiers.',
        ],
    },
    {
        'title': 'Architecture Low-Level Slice',
        'body': [
            'GitLab CI jobs assume scoped OIDC roles for cloud deployment.',
            'Terraform state stored securely with KMS and restricted access.',
            'Application deployed to private subnets with ALB and no public SSH.',
            'RDS services use private connectivity, enforced TLS, and key-managed encryption.',
        ],
    },
    {
        'title': 'Pipeline Design',
        'body': [
            'Preflight: Terraform fmt and validate to catch syntax early.',
            'Secrets scan: Gitleaks prevents committed credentials from merging.',
            'IaC scanning: Checkov, Trivy, and OPA enforce policies before deploy.',
            'SCA/SBOM: vulnerability scanning and bill of materials generation.',
            'Container scan: image vulnerability and signature verification.',
        ],
    },
    {
        'title': 'Drift and Detection',
        'body': [
            'Scheduled drift detection with Checkov regularly scans infrastructure configuration.',
            'Centralised logging and alerting through Sentinel and provider-native controls.',
            'Findings feed into a shared backlog for prioritised remediation.',
            'Exception register and quarterly review for residual risk.',
        ],
    },
    {
        'title': 'COTS Exception and Compensating Controls',
        'body': [
            'The COTS tool cannot use storage encryption in its current version.',
            'Compensating controls: private isolation, strict IAM, real-time logging, and review.',
            'Formal approval with a 12-month expiry and remediation commitment.',
        ],
    },
    {
        'title': '90-Day Remediation Roadmap',
        'body': [
            'Weeks 1–2: rotate credentials, restrict IAM, isolate public workloads.',
            'Weeks 3–6: deploy the shared security pipeline and enable detection.',
            'Weeks 7–12: complete encryption hardening, custom policies, and exception documentation.',
            'Finish with formal evidence that all Critical findings are remediated or controlled.',
        ],
    },
    {
        'title': 'Preventing Recurrence',
        'body': [
            'Shared CI/CD components enforce guardrails across all workloads.',
            'OPA policies encode cross-cloud governance decisions in one rule set.',
            'Central detection, periodic sweeps, and exception management maintain ongoing resilience.',
        ],
    },
    {
        'title': 'Conclusion',
        'body': [
            'The programme can reach a secure target state with focused execution this quarter.',
            'The change is not only technical: it is a stronger governance and operating model.',
            'The next step is immediate remediation on Critical findings and enforcing the pipeline across the estate.',
        ],
    },
]

CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
'''
for index in range(2, len(SLIDES) + 1):
    CONTENT_TYPES += f'  <Override PartName="/ppt/slides/slide{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>\n'
CONTENT_TYPES += '''  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
'''

ROOT_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
'''

PRESENTATION_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldIdLst>
'''
for idx, _ in enumerate(SLIDES, start=1):
    PRESENTATION_XML += f'    <p:sldId id="{256 + idx}" r:id="rId{idx}"/>\n'
PRESENTATION_XML += '''  </p:sldIdLst>
  <p:sldSz cx="9144000" cy="6858000"/>
  <p:notesSz cx="6858000" cy="9144000"/>
  <p:sldMasterIdLst>
    <p:sldMasterId r:id="rIdMaster"/>
  </p:sldMasterIdLst>
</p:presentation>
'''

PRESENTATION_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
'''
for idx, _ in enumerate(SLIDES, start=1):
    PRESENTATION_RELS += f'  <Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{idx}.xml"/>\n'
PRESENTATION_RELS += '''  <Relationship Id="rIdMaster" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
</Relationships>
'''

MASTER_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr/>
    </p:spTree>
  </p:cSld>
  <p:sldLayoutIdLst>
    <p:sldLayoutId id="1" r:id="rId1"/>
  </p:sldLayoutIdLst>
</p:sldMaster>
'''

MASTER_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>
'''

LAYOUT_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="Title 1"/>
          <p:cNvSpPr txBox="1"/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr/>
        <p:txBody>
          <a:bodyPr/>
          <a:lstStyle/>
          <a:p>
            <a:pPr lvl="0"/><a:r><a:rPr lang="en-US" sz="4400" b="1"/></a:r>
          </a:p>
        </p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="3" name="Content 1"/>
          <p:cNvSpPr txBox="1"/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr/>
        <p:txBody>
          <a:bodyPr wrap="square"/>
          <a:lstStyle>
            <a:lvl1pPr marL="0" indent="0"/>
          </a:lstStyle>
          <a:p>
            <a:pPr lvl="0" buChar="•"/><a:r><a:rPr lang="en-US" sz="3200"/></a:r>
          </a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sldLayout>
'''

THEME_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office Theme">
  <a:themeElements>
    <a:clrScheme name="Office">
      <a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>
      <a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="1F4E79"/></a:dk2>
      <a:lt2><a:srgbClr val="BFCBDB"/></a:lt2>
      <a:accent1><a:srgbClr val="1a365d"/></a:accent1>
      <a:accent2><a:srgbClr val="2c5282"/></a:accent2>
      <a:accent3><a:srgbClr val="4a90e2"/></a:accent3>
      <a:accent4><a:srgbClr val="8ab2d3"/></a:accent4>
      <a:accent5><a:srgbClr val="e2e8f0"/></a:accent5>
      <a:accent6><a:srgbClr val="f7fafc"/></a:accent6>
      <a:hlink><a:srgbClr val="1a365d"/></a:hlink>
      <a:folHlink><a:srgbClr val="2c5282"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="Office">
      <a:majorFont>
        <a:latin typeface="Calibri"/>
        <a:ea typeface=""/>
        <a:cs typeface=""/>
      </a:majorFont>
      <a:minorFont>
        <a:latin typeface="Calibri"/>
        <a:ea typeface=""/>
        <a:cs typeface=""/>
      </a:minorFont>
    </a:fontScheme>
    <a:fmtScheme>
      <a:fillStyle>
        <a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>
        <a:gradFill rotWithShape="1"><a:gsLst><a:gs pos="0"><a:schemeClr val="phClr"/></a:gs><a:gs pos="100"><a:schemeClr val="phClr"><a:lumMod val="65000"/></a:schemeClr></a:gs></a:gsLst><a:lin ang="16200000" scaled="1"/></a:gradFill>
        <a:gradFill rotWithShape="1"><a:gsLst><a:gs pos="0"><a:schemeClr val="phClr"/><a:lumMod val="65000"/></a:gs><a:gs pos="100"><a:schemeClr val="phClr"/><a:lumMod val="45000"/></a:gs></a:gsLst><a:lin ang="16200000" scaled="1"/></a:gradFill>
      </a:fillStyle>
      <a:lnStyle>
        <a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:miter lim="800000"/></a:ln>
        <a:ln w="25400"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:miter lim="800000"/></a:ln>
        <a:ln w="38100"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:miter lim="800000"/></a:ln>
      </a:lnStyle>
      <a:effectStyle>
        <a:effectLst/>
      </a:effectStyle>
      <a:bgFillStyle>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
      </a:bgFillStyle>
    </a:fmtScheme>
  </a:themeElements>
</a:theme>
'''

DOC_PROPS_CORE = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>DevSecOps Assessment Presentation</dc:title>
  <dc:subject>Multi-cloud DevSecOps security assessment</dc:subject>
  <dc:creator>DevSecOps Team</dc:creator>
  <cp:lastModifiedBy>DevSecOps Team</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">2026-08-03T00:00:00Z</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">2026-08-03T00:00:00Z</dcterms:modified>
</cp:coreProperties>
'''

DOC_PROPS_APP = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Microsoft PowerPoint</Application>
  <PresentationFormat>On-screen Show</PresentationFormat>
  <OutlineCount>{}</OutlineCount>
</Properties>
'''.format(len(SLIDES))

SLIDE_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="Title 1"/>
          <p:cNvSpPr txBox="1"/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="457200" y="457200"/><a:ext cx="8233200" cy="1097280"/></a:xfrm>
        </p:spPr>
        <p:txBody>
          <a:bodyPr/>
          <a:lstStyle/>
          <a:p>
            <a:pPr><a:defRPr lang="en-US" sz="6200" b="1"/></a:pPr>
            <a:r><a:rPr lang="en-US" sz="6200" b="1"/><a:t>{title}</a:t></a:r>
          </a:p>
        </p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="3" name="Content 1"/>
          <p:cNvSpPr txBox="1"/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="457200" y="1828800"/><a:ext cx="8233200" cy="3900000"/></a:xfrm>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square"/>
          <a:lstStyle>
            <a:lvl1pPr marL="0" indent="0"/>
            <a:lvl2pPr marL="45720" indent="0"/>
          </a:lstStyle>
          {body}
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>
'''


def make_paragraphs(lines):
    parts = []
    for line in lines:
        if line.startswith('  '):
            text = escape(line.strip())
            parts.append(f'<a:p><a:pPr lvl="1" buChar="•"/><a:r><a:rPr lang="en-US" sz="2800"/></a:r><a:t>{text}</a:t></a:p>')
        else:
            text = escape(line)
            parts.append(f'<a:p><a:pPr lvl="0" buChar="•"/><a:r><a:rPr lang="en-US" sz="3200"/></a:r><a:t>{text}</a:t></a:p>')
    return ''.join(parts)


def create_slide(title, body_lines):
    return SLIDE_TEMPLATE.format(title=escape(title), body=make_paragraphs(body_lines))

with zipfile.ZipFile('DevSecOps_Presentation.pptx', 'w', compression=zipfile.ZIP_DEFLATED) as ppt:
    ppt.writestr('[Content_Types].xml', CONTENT_TYPES)
    ppt.writestr('_rels/.rels', ROOT_RELS)
    ppt.writestr('ppt/presentation.xml', PRESENTATION_XML)
    ppt.writestr('ppt/_rels/presentation.xml.rels', PRESENTATION_RELS)
    ppt.writestr('ppt/slideMasters/slideMaster1.xml', MASTER_XML)
    ppt.writestr('ppt/slideMasters/_rels/slideMaster1.xml.rels', MASTER_RELS)
    ppt.writestr('ppt/slideLayouts/slideLayout1.xml', LAYOUT_XML)
    ppt.writestr('ppt/theme/theme1.xml', THEME_XML)
    for idx, slide in enumerate(SLIDES, start=1):
        ppt.writestr(f'ppt/slides/slide{idx}.xml', create_slide(slide['title'], slide['body']))
    ppt.writestr('docProps/core.xml', DOC_PROPS_CORE)
    ppt.writestr('docProps/app.xml', DOC_PROPS_APP)

print('Created DevSecOps_Presentation.pptx')
