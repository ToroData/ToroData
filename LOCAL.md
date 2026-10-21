# Ricard S. Raigada-García — academic website

Static site (HTML + CSS, no build step). Hosted on GitHub Pages.

## Edit
- Content: `index.html` (each section is clearly marked; talks/posters have a copy-paste template inside an HTML comment).
- Style: `style.css` (colours at the top in `:root`).
- Photo: replace `assets/photo.png` (square image, ~400×400).
- CV: drop a `cv.pdf` in the root. Until it exists, "Download CV" opens the print dialog
  and the page prints as a clean CV (choose "Save as PDF").
- Posters/slides: put PDFs in `assets/posters/` and `assets/slides/` and link them.

## Preview locally

    python3 -m http.server 8080   # then open http://localhost:8080

## Publish on GitHub Pages (free)
1. Create a repo named `<your-username>.github.io` (gives you https://<your-username>.github.io).
2. Upload these files to it.
3. Settings → Pages → Source: "Deploy from a branch", branch `main`, folder `/ (root)`.
4. Add the URL to your ORCID ("Websites & social links") and LinkedIn.
