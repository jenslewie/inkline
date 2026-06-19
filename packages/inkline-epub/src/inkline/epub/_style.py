from __future__ import annotations

BOOK_CSS = """
body {
  font-family: "Songti SC", STSong, "Noto Serif CJK SC", serif;
  line-height: 1.7;
  margin: 0;
  padding: 0;
}
main {
  max-width: 42em;
  margin: 0 auto;
  padding: 1.4em 5% 2.2em;
}
p {
  text-indent: 2em;
  margin: 0 0 0.8em;
  text-align: justify;
}
h1, h2, h3, h4, h5, h6 {
  text-align: center;
}
table {
  border-collapse: collapse;
  width: 100%;
}
td, th {
  border: 1px solid #999;
  padding: 0.25em 0.4em;
}
.td-align-center { text-align: center; }
.td-align-right { text-align: right; }
.td-align-left { text-align: left; }
.table-notes {
  margin-top: 0.5em;
  margin-bottom: 1.2em;
  font-size: 0.85em;
}
.table-note {
  text-indent: 0;
  margin: 0.2em 0;
}
figure {
  margin: 1em 0;
  text-align: center;
}
img {
  display: block;
  height: auto;
  margin: 0 auto;
  max-width: 100%;
}
.image-placeholder {
  border: 1px solid #aaa;
  padding: 0.75em;
  color: #555;
  background: #f7f7f7;
}
figcaption {
  font-family: "Kaiti SC", STKaiti, KaiTi, FangSong, STFangsong, serif;
  font-size: 0.85em;
  line-height: 1.4;
  margin-top: 0.5em;
  text-align: left;
  text-indent: 0;
}
figcaption p {
  margin: 0 0 0.3em;
}
.caption-title {
  text-indent: 0;
  font-family: inherit;
  font-size: inherit;
  font-weight: 700;
  margin: 0 0 0.3em;
}
.caption-body {
  text-indent: 2em;
  font-family: inherit;
  font-size: inherit;
  margin: 0 0 0.3em;
}
.figure-block {
  break-inside: avoid;
  page-break-inside: avoid;
}
.figure-block img {
  max-height: 85vh;
  width: auto;
}
.figure-block.has-caption img {
  max-height: 70vh;
  max-height: calc(100vh - 8em);
}
.figure-block.has-caption.caption-long img {
  max-height: 52vh;
  max-height: min(52vh, calc(100vh - 14em));
}
.figure-block.has-caption figcaption {
  break-before: avoid;
  page-break-before: avoid;
}
.figure-block.caption-side {
  text-align: left;
}
.figure-block.caption-side img {
  display: inline-block;
  max-width: 58%;
  max-height: 78vh;
  vertical-align: top;
}
.figure-block.caption-side figcaption {
  display: inline-block;
  width: 36%;
  margin-top: 0;
  margin-left: 1em;
  vertical-align: top;
}
.caption {
  font-family: "Kaiti SC", STKaiti, KaiTi, FangSong, STFangsong, serif;
  font-size: 0.85em;
  text-align: left;
  margin: 0.2em 0 0.8em;
  text-indent: 0;
}
.display-block {
  font-family: "Kaiti SC", STKaiti, KaiTi, FangSong, STFangsong, serif;
  font-size: 0.85em;
  margin: 1.2em 2em;
}
.display-block-paragraph {
  font-family: "Kaiti SC", STKaiti, KaiTi, FangSong, STFangsong, serif;
  font-size: inherit;
  text-indent: 2em;
  margin: 0 0 0.5em;
  text-align: justify;
}
.display-block-standalone {
  margin-top: 1.6em;
  margin-bottom: 1.6em;
}
.display-block-signature {
  font-size: 1em;
  margin: 1.2em 0;
  text-align: right;
}
.display-block-signature .display-block-paragraph {
  font-family: "Kaiti SC", STKaiti, KaiTi, FangSong, STFangsong, serif;
  text-indent: 0;
  text-align: right;
}
.chapter-title-page {
  text-align: center;
  box-sizing: border-box;
  padding: 25vh 0 0;
  min-height: 90vh;
  break-after: always;
  page-break-after: always;
}
""".strip()
