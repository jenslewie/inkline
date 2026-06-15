from __future__ import annotations

BOOK_CSS = """
body {
  font-family: serif;
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
  font-size: 0.9em;
  line-height: 1.4;
  margin-top: 0.5em;
  text-align: center;
  text-indent: 0;
}
.figure-block {
  break-inside: avoid;
  page-break-inside: avoid;
}
.figure-block img {
  max-height: 85vh;
}
.caption {
  font-size: 0.9em;
  text-align: center;
  margin: 0.2em 0 0.8em;
  text-indent: 0;
}
.display-block {
  margin: 1.2em 2em;
  text-indent: 0;
  white-space: pre-line;
  font-family: sans-serif;
}
.display-block-standalone {
  margin-top: 1.6em;
  margin-bottom: 1.6em;
}
.display-block-right {
  margin: 1.2em 0;
  text-align: right;
  text-indent: 0;
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
