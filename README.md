# loconotion

Notion.so is a popular application where you can create your own workspace. It's very easy to use. Notion also offer the possibility of making a page (and its sub-page) public on the web and because of this several people choose to use Notion to manage their personal blog, portfolio, or some kind of simple website. Notion however does not support custom domains when doing so: your pages are stuck in the `notion.so` domain, and computer-generated urls and slugs.

Some services like Super, HostingPotion, HostNotion and Fruition cleverly tried to work around this issue by relying on a clever hack using CloudFlare workers. This solution, however, has some disadvantages:

- Not free (Super, HostingPotion and HostNotion all take a monthly fee: Fruition is open-sourced but any domain with a decent amount of daily visit will soon clash against CloudFlare's free tier limitations, and force you to upgrade to the 5$ or more plan.)
- As the page is still hosted on Notion, it comes bundled with all their analytics, editing / collaboration javascript, vendors css, and more bloat which causes the page to load at speeds that are not exactly appropriate to a simple blog / website. Running [this](https://www.notion.so/The-perfect-It-s-Always-Sunny-in-Philadelphia-episode-d08aaec2b24946408e8be0e9f2ae857e) example page on Google's [PageSpeed Insights](https://developers.google.com/speed/pagespeed/insights/) scores a measly 24 / 66 on mobile / desktop.

Enter Loconotion!

Loconotion is a tool that approach this a bit differently. It lets Notion render the page, then parses it and saves a static version of the page to disk. While doing so, it strips out all the unnecessary bloat, and adds some extra css and js to keep the nice features like mobile responsiveness working. It also saves all related images / assets, and parses any subpage as well while keeping links intact, and cleaning up the urls. The result? A faster, self-contained version of the page that keeps all of Notion's nice layouts and eye candies, ready to be deployed on your CDN of choice. For a comparison, the same example page parsed with Loconotion and deployed on Netflify's free tier achieves a PageSpeed Insight score of 96 / 100!

This approach also offers the advantage of being able to inject anything in th pages, from custom fonts to additional meta tags for SEO, or custom analytics.

However, bear in mind that as we are effectively parsing a static version of the page, the following features will not work:
- All pages will open in their own page and not modals (this could be a pro, depending on how you look at it)
- Databases will be presented in their initial view - no switching views from table to gallery, for example.
- All editing features will be disabled - no ticking checkboxes or dragging kanban boards cards around. Usually not an issue as public pages usually have changes locked.
- Dynamic elements won't update automatically - for example, the calendar will not highlight the current date.

Everything else, like embedding and dropdowns should work as expected.