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
  break-inside: avoid;
  page-break-inside: avoid;
  -webkit-column-break-inside: avoid;
}
img {
  display: block;
  height: auto;
  margin: 0 auto;
  max-width: 100%;
  break-inside: avoid;
  page-break-inside: avoid;
  -webkit-column-break-inside: avoid;
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
  display: block;
  max-width: 100%;
  width: 100%;
  break-inside: avoid;
  page-break-inside: avoid;
  -webkit-column-break-inside: avoid;
}
.figure-page-break {
  display: block;
  height: 0;
  line-height: 0;
  margin: 0;
  padding: 0;
  break-after: page;
  page-break-after: always;
  -webkit-column-break-after: always;
}
.figure-block img {
  max-height: 32em;
  max-height: 70vh;
  width: auto;
  break-after: avoid;
  page-break-after: avoid;
}
.figure-block.figure-fullwidth img {
  width: auto;
  max-width: 100%;
  max-height: 32em;
  max-height: calc(100vh - 4em);
}
.figure-block.has-caption img {
  width: auto;
  max-width: 100%;
  height: auto;
  max-height: 32em;
  max-height: calc(100vh - 8em);
}
.figure-block.has-caption figcaption {
  break-before: avoid;
  page-break-before: avoid;
}
.figure-block.caption-side {
  display: -webkit-box;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  width: 100%;
  text-align: left;
  gap: 1em;
}
.figure-block.caption-side .figure-side-image {
  min-width: 0;
  text-align: center;
  flex-grow: 0;
  flex-shrink: 1;
}
.figure-block.caption-side .figure-side-image img {
  display: block;
  max-width: 100%;
  height: auto;
  max-height: 32em;
  max-height: calc(100vh - 8em);
  margin: 0 auto;
}
.figure-block.caption-side figcaption {
  min-width: 0;
  margin-top: 0;
  flex-grow: 0;
  flex-shrink: 1;
}
@media all and (max-width: 42em) {
  .figure-block.caption-side {
    display: block;
  }
  .figure-block.caption-side .figure-side-image {
    display: block;
    width: 100%;
  }
  .figure-block.caption-side figcaption {
    display: block;
    width: auto;
    margin-top: 0.6em;
  }
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
