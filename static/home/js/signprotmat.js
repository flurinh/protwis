// * CONSTANTS
var margin = { top: 0, right: 150, bottom: 180, left: 130 };
var w = 650 - margin.left - margin.right, h = 550 - margin.top - margin.bottom;
// * DATA
var dataset = interactions;
// dummy data for testing purposes
var add1 = [, "56.51x51", , , , , "G.H5.14"];
var add2 = [, "67.51x51", , , , , "G.X6.66"];
var add3 = [, "34.52x51", , , , , "G.H2.03"];
var add4 = [, "7.51x51", , , , , "G.H5.06"];
var add5 = [, "7.51x52", , , , , "G.Y1.23"];
// https://stackoverflow.com/a/20808090/8160230
var data_t = dataset.slice();
// add dummy data to dataset
data_t.push(add1, add2, add3, add4, add5);
var keys = [
    "rec_sn",
    "rec_gn",
    "rec_aa",
    "pdb_id",
    "int_ty",
    "sig_sn",
    "sig_gn",
    "sig_aa"
];
data_t = data_t.map(function (e) {
    var obj = {};
    keys.forEach(function (key, i) {
        obj[key] = e[i];
    });
    return obj;
});
// * DEFINE ADDITIONAL DATASETS
// the next two datasets could also be generated by _.uniqBy lodash
// data that has unique receptor__generic_name entries
var data_t_rec = data_t.filter(function (thing, index, self) {
    return index === self.findIndex(function (t) { return t.rec_gn === thing.rec_gn; });
});
// data that has unique sigprot__generic_name entries
var data_t_sig = data_t.filter(function (thing, index, self) {
    return index === self.findIndex(function (t) { return t.sig_gn === thing.sig_gn; });
});
// interaction types
var int_ty = d3.map(data_t, function (d) { return d.int_ty; }).keys();
var rm_index = int_ty.indexOf("undefined");
if (rm_index > -1) {
    int_ty.splice(rm_index, 1);
}
// * SETTING UP SVG FOR OUTPUT
var svg = d3
    .select("body")
    .select("div#content")
    .append("div")
    .classed("svg-container", true) //container class to make it responsive
    .append("svg")
    .attr("preserveAspectRatio", "xMinYMin meet")
    .attr("viewBox", "0 0 " +
    (w + margin.left + margin.right) +
    " " +
    (h + margin.top + margin.bottom))
    .classed("svg-content", true) //class to make it responsive
    .append("g")
    .attr("transform", "translate(" + margin.left + "," + margin.top + ")");
// * SETTING THE X/Y SCALE
var xScale = d3
    .scaleBand()
    .domain(d3
    .map(data_t, function (d) { return d.rec_gn; })
    .keys()
    .sort(d3.ascending))
    .range([0, w])
    // .round(true)
    .padding(1);
var yScale = d3
    .scaleBand()
    .domain(d3
    .map(data_t, function (d) { return d.sig_gn; })
    .keys()
    .sort(d3.descending))
    .range([h, 0])
    // .round(true)
    .padding(1);
// * SETTING THE COLOR SCALE
var colScale = d3
    .scaleOrdinal()
    .domain(int_ty)
    .range(d3.schemeDark2);
// * DEFINING AXIS FOR X/Y AND GRID
var xAxis = d3
    .axisBottom(xScale)
    .tickSize(0)
    .tickPadding(8);
var yAxis = d3
    .axisRight(yScale)
    .tickSize(0)
    .tickPadding(8);
var xAxisGrid = d3
    .axisTop(xScale)
    .tickSize(h - yScale.step())
    .tickFormat(function (d) { return ""; });
var yAxisGrid = d3
    .axisRight(yScale)
    .tickSize(w - xScale.step())
    .tickFormat(function (d) { return ""; });
// * ADD TOOLTIP FUNCTIONALITY
var tip = d3
    .tip()
    .attr("class", "d3-tip")
    .html(function (d) {
    return d.rec_gn + "<br>" + d.sig_gn + "<br>" + d.int_ty;
});
svg.call(tip);
// * RENDER DATA
var shift_left = 7 / 8;
var shift_top = 1 / 8;
var scale_size = shift_left - shift_top;
var offset = 1;
// array for data in infobox
var info_data = [];
svg
    .append("g")
    .attr("id", "interact")
    .selectAll("rects")
    .data(data_t)
    .enter()
    .append("rect")
    .attr("x", function (d) {
    return xScale(d.rec_gn) - shift_left * xScale.step() + offset;
})
    .attr("y", function (d) {
    return yScale(d.sig_gn) + shift_top * yScale.step() + offset;
})
    .attr("rx", function () {
    if (data_t.length < 15) {
        return 5;
    }
    else {
        return 3;
    }
})
    .attr("ry", function () {
    if (data_t.length < 15) {
        return 5;
    }
    else {
        return 3;
    }
})
    .attr("width", xScale.step() * scale_size)
    .attr("height", yScale.step() * scale_size)
    .attr("fill", function (d) {
    if (d.int_ty === undefined) {
        return "none";
    }
    else {
        return colScale(d.int_ty);
    }
})
    .on("mouseover", function (d) {
    tip.show(d);
})
    .on("mouseout", function (d) {
    tip.hide();
})
    .on("click", function (d) {
    var index;
    // var rect_x = d3.event.target.getAttribute('x')
    // var rect_y = d3.event.target.getAttribute('y')
    // console.log(rect_x, rect_y)
    // https://stackoverflow.com/a/20251369/8160230
    // select the rect under cursor
    var curr = d3.select(this);
    // Determine if current rect was clicked before
    var active = d.active ? false : true;
    // Update whether or not the elements are active
    d.active = active;
    // set style in regards to active
    if (d.active) {
        curr.style("stroke", "black").style("stroke-width", 2);
        info_data.push(d);
    }
    else {
        curr.style("stroke", "none").style("stroke-width", 2);
        index = info_data.indexOf(d);
        info_data.splice(index, 1);
    }
    infoBoxUpdate();
});
// * ADD INFOBOX ELEMENT
svg
    .append("g")
    .attr("id", "infobox")
    .attr("transform", "translate(-15," + (int_ty.length + 2) * 20 + ")");
function infoBoxUpdate() {
    // create selection and bind data
    var info_box = d3
        .select("g#infobox")
        .selectAll("text")
        .data(info_data);
    // update existing nodes
    info_box
        .attr("y", function (d, i) {
        return i * 15;
    })
        .attr("text-anchor", "end")
        .attr("class", "legend");
    // create nodes for new data
    info_box
        .enter()
        .append("text")
        .attr("y", function (d, i) {
        return i * 15;
    })
        .attr("text-anchor", "end")
        .attr("class", "legend")
        .text(function (d) {
        return d.rec_gn + " : " + d.sig_gn;
    });
    // discard removed nodes
    info_box.exit().remove();
    // print the data again in case it changed
    info_box.text(function (d) {
        return d.rec_gn + " : " + d.sig_gn;
    });
}
// * ADDING COLOR LEGEND
svg
    .append("g")
    .attr("class", "legendOrdinal")
    .attr("transform", "translate(-30," + yScale.step() + ")");
var legendOrdinal = d3
    .legendColor()
    .cells(int_ty.length)
    .scale(colScale)
    // .cellFilter(function (d) { return d.label !== "undefined" })
    .orient("vertical")
    .labelOffset(-20);
svg
    .select(".legendOrdinal")
    .call(legendOrdinal)
    .selectAll("rect")
    .attr("rx", 3)
    .attr("ry", 3);
svg
    .select(".legendOrdinal")
    .selectAll("text")
    .attr("class", "legend")
    .attr("text-anchor", "end");
// * APPENDING AMINOACID SEQUENCE [RECEPTOR]
svg
    .append("g")
    .attr("id", "recAA")
    .attr("transform", "translate(" + -xScale.step() / 2 + "," + h + ")")
    .selectAll("text")
    .data(data_t_rec)
    .enter()
    .append("text")
    .attr("x", function (d) {
    return xScale(d.rec_gn);
})
    .attr("text-anchor", "middle")
    .attr("dy", 75)
    .text(function (d) {
    return d.rec_aa;
});
// * APPENDING AMINOACID SEQUENCE [SIGPROT]
svg
    .append("g")
    .attr("id", "sigAA")
    .attr("transform", "translate(" + (w + (1 / 3) * margin.right) + "," + yScale.step() / 2 + ")")
    .selectAll("text")
    .data(data_t_sig)
    .enter()
    .append("text")
    .attr("y", function (d) {
    return yScale(d.sig_gn);
})
    .attr("text-anchor", "middle")
    .attr("dy", 5)
    .text(function (d) {
    return d.sig_aa;
});
// * AMINOACID SEQUENCE BOX
var seq_rect_h = 20;
d3.select("g#recAA")
    .append("rect")
    .style("stroke", "black")
    .style("fill", "none")
    .attr("x", yScale.step() / 2)
    .attr("y", 60)
    .attr("width", w - xScale.step())
    .attr("height", seq_rect_h);
d3.select("g#sigAA")
    .append("rect")
    .style("stroke", "black")
    .style("fill", "none")
    .attr("x", -seq_rect_h / 2)
    .attr("y", yScale.step() / 2)
    .attr("width", seq_rect_h)
    .attr("height", h - yScale.step());
// * DRAWING AXES
svg
    .append("g")
    .attr("class", "x axis")
    .attr("transform", "translate(" + -xScale.step() / 2 + "," + h + ")")
    .call(xAxis)
    .selectAll("text")
    .attr("text-anchor", "end")
    .attr("font-size", "12px")
    .attr("dx", "-5px")
    .attr("dy", "-5px")
    .attr("transform", "rotate(-90)");
svg
    .append("g")
    .attr("class", "y axis")
    .attr("transform", "translate(" + (w - xScale.step()) + "," + yScale.step() / 2 + ")")
    .call(yAxis)
    .selectAll("text")
    .attr("font-size", "12px");
// * DRAWING GRIDLINES
svg
    .append("g")
    .attr("class", "x grid")
    .attr("transform", "translate(" + 0 + "," + h + ")")
    .call(xAxisGrid);
svg
    .append("g")
    .attr("class", "y grid")
    .attr("transform", "translate(" + 0 + "," + yScale.step() + ")")
    .call(yAxisGrid);
// * ADDITIONAL FIGURE LINES
// top x line
svg
    .append("line")
    .style("stroke", "black")
    .attr("x1", 0)
    .attr("y1", yScale.step())
    .attr("x2", w - xScale.step())
    .attr("y2", yScale.step());
// left y line
svg
    .append("line")
    .style("stroke", "black")
    .attr("x1", 0)
    .attr("y1", yScale.step())
    .attr("x2", 0)
    .attr("y2", h);
// * ADD AXIS LABELS
svg
    .append("text")
    .attr("class", "x label")
    .attr("text-anchor", "end")
    .attr("x", 0)
    .attr("y", h + 15)
    .text("GPCR");
svg
    .append("text")
    .attr("class", "y label")
    .attr("text-anchor", "begin")
    .attr("x", w - 0.8 * xScale.step())
    .attr("y", 0.8 * yScale.step())
    .text("G-Protein");
// debugging purposes to inspect data
// https://stackoverflow.com/a/9507713/8160230
function tabulate(data, columns) {
    var table = d3
        .select("div#content")
        .append("table")
        .attr("width", 2 * w);
    var thead = table.append("thead");
    var tbody = table.append("tbody");
    // append the header row
    thead
        .append("tr")
        .selectAll("th")
        .data(columns)
        .enter()
        .append("th")
        .text(function (column) {
        return column;
    });
    // create a row for each object in the data
    var rows = tbody
        .selectAll("tr")
        .attr("padding-right", "10px")
        .data(data)
        .enter()
        .append("tr");
    // create a cell in each row for each column
    var cells = rows
        .selectAll("td")
        .data(function (row) {
        return columns.map(function (column) {
            return { column: column, value: row[column] };
        });
    })
        .enter()
        .append("td")
        .text(function (d) {
        return d.value;
    });
    return table;
}
// render the table(s)
// tabulate(data_t, keys);
