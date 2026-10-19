(function (root, factory) {
  const api = factory();
  root.DeskQueries = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const HASH = {
    deals: "591b0e6d036c2120c8f95b97dbfdf5635df3747cd901f4895e009935229417ef",
    deal: "d0421fb8dea49652876d69b1a14ce2c715ea9c7127c48c85a78e06de31a845ae",
    items: "3f20c731f8f769a094ee3fa32e09f8e12250357e9a4f0ebb4e6988e7a0bb9260",
    itemPriorityStatuses: "b922220c6f979537e1b99de6af8f5c13727daeff66727f679f07f986ce1c025a",
    userChats: "c1ddbcd7c8b87160ac25e0734f9dc32fc945287b056f4b14abf1473bfb1ad11a",
  };

  const DOC = {
    viewer: "query viewer { viewer { id username } }",
    deals: `query deals($pagination: Pagination, $filter: ItemDealFilter!, $showForbiddenImage: Boolean) {
      deals(pagination: $pagination, filter: $filter) {
        edges { node { id status direction hasProblem isAutomated commentFromBuyer
          user { id username }
          item { id name price status category { name } user { id } }
        } }
        pageInfo { endCursor hasNextPage }
      }
    }`,
    deal: `query deal($id: UUID!, $hasSupportAccess: Boolean!, $showForbiddenImage: Boolean) {
      deal(id: $id) {
        id status direction hasProblem isAutomated commentFromBuyer
        user { id username }
        chat { id }
        item { id name price status category { id name } user { id } obtainingType { id name } }
        obtainingFields { id label value required hidden }
      }
    }`,
    items: `query items($filter: ItemFilter, $pagination: Pagination, $showForbiddenImage: Boolean) {
      items(filter: $filter, pagination: $pagination) {
        edges { node { id name price status priorityPosition } }
        pageInfo { endCursor hasNextPage }
      }
    }`,
    itemPriorityStatuses: `query itemPriorityStatuses($price: NonNegativeFloat!, $itemId: UUID) {
      itemPriorityStatuses(price: $price, itemId: $itemId) { id price name type }
    }`,
    userChats: `query userChats($pagination: Pagination, $filter: ChatFilter) {
      chats(pagination: $pagination, filter: $filter) {
        edges { node { id participants { id username }
          lastMessage { id text createdAt user { id username } } } }
      }
    }`,
    updateDeal: `mutation updateDeal($input: UpdateItemDealInput!) {
      updateDeal(input: $input) { id status }
    }`,
    createChatMessage: `mutation createChatMessage($input: CreateChatMessageInput!) {
      createChatMessage(input: $input) { id text }
    }`,
    publishItem: `mutation publishItem($input: PublishItemInput!) {
      publishItem(input: $input) { id status }
    }`,
    increaseItemPriorityStatus: `mutation increaseItemPriorityStatus($input: PublishItemInput!) {
      increaseItemPriorityStatus(input: $input) { id status priorityPosition }
    }`,
  };

  return { HASH, DOC };
});
