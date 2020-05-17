console.log(`
Hello! I am running from a script injected on the page by Loconotion 🎉
This could be an analytics script, real-time chat support script, or anything you want really.
`);
fetch("https://api.quotable.io/random")
  .then((data) => {
    return data.json();
  })
  .then((response) => {
    console.log("Here's a quote for your time:");
    console.log(response.content + "  --" + response.author);
  })
  .catch((error) => {
    console.log(error);
  });
