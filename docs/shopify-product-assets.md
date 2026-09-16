# Shopify product assets

## Verified access

The user's `.env` contains `SHOPIFY_SHOP_DOMAIN` and
`SHOPIFY_ADMIN_ACCESS_TOKEN`. Read-only Admin GraphQL access was verified for
`msdressly.myshopify.com` on 2026-09-15, using API version `2026-04`.
Keep the token in the ignored environment file; never include it in prompts,
media exports, command arguments, logs, or receipts.

The first selected product is **Women's Black and White Checkerboard Tank Top**,
Shopify product `9381136597248`. Its complete attached media list contains:

- One 1365 × 2048 product image, matching the public product page.
- No attached video, external video, 3D model, or additional product angle.
- A product description with fit guidance and outfit suggestions.

This check covers media attached to that product. It is not an inventory of
every file elsewhere in the store, and does not establish access to unrelated
administrative data.

## Reference intake

1. Resolve the user-selected product by its exact handle or product ID.
2. Query only the product fields needed for production: identity, description,
   and attached media. Follow media pagination before declaring the list complete.
3. Preserve product IDs and media IDs with source URLs and the retrieval date.
4. Download the selected assets, inspect them, and distinguish visible product
   facts from proposed styling. Do not invent unshown garment details or claims.
5. Import suitable images into Jimeng through the official Canvas CLI, then
   bind the imported image node as a generation reference.
6. Use only necessary product data in generation requests. Shopify credentials
   never go to the generation service.

The verified pilot query was checked against the Shopify Admin GraphQL schema.
References: [product search](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/products)
and [media metadata](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/files).

## Local evidence

Under `data/production/v-product-variation-Db9SrsBsIUg/product/`:

- `product-reference.graphql`: validated read-only query.
- `shopify-product.json`: product description and complete attached-media result.
- `description.html`: product description snapshot.
- `source.json`: public product-image provenance.
- `msdressly-checkerboard-tank-product-01.jpg`: inspected image.

These artifacts are ignored by Git. No Shopify products or settings were changed.
Access is verified for agent-directed intake; an automatic Shopify-to-production
importer has not been added to the application's pipeline.
