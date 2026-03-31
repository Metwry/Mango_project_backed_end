from django.test import SimpleTestCase

from news.service.yahoo_news import (
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    TableBlock,
    extract_article_blocks,
    render_blocks_text,
)


class YahooNewsParsingTests(SimpleTestCase):
    def test_extract_article_blocks_preserves_structured_content(self) -> None:
        page_html = """
        <html>
          <body>
            <article>
              <h1>Sample Title</h1>
              <p>Intro paragraph.</p>
              <h2>Highlights</h2>
              <ul>
                <li>First point</li>
                <li>Second point</li>
              </ul>
              <table>
                <tr>
                  <th>Lender</th>
                  <th>Maximum amount</th>
                </tr>
                <tr>
                  <td>Best Egg</td>
                  <td>$50,000</td>
                </tr>
              </table>
              <p>This article was originally published by Example.</p>
            </article>
          </body>
        </html>
        """

        blocks = extract_article_blocks(page_html, article_title="Sample Title")

        self.assertIsInstance(blocks[0], ParagraphBlock)
        self.assertIsInstance(blocks[1], HeadingBlock)
        self.assertIsInstance(blocks[2], ListBlock)
        self.assertIsInstance(blocks[3], TableBlock)

        content = render_blocks_text(blocks)
        self.assertIn("Intro paragraph.", content)
        self.assertIn("## Highlights", content)
        self.assertIn("- First point", content)
        self.assertIn("| Lender | Maximum amount |", content)
        self.assertIn("| Best Egg | $50,000 |", content)
        self.assertNotIn("originally published", content.lower())
