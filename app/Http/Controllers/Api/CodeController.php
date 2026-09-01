<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use Illuminate\Http\Request;
use App\Models\Code;
use App\Traits\CrudOperations;

class CodeController extends Controller
{
    use CrudOperations;

    protected $model = Code::class;

    /**
     * 코드 목록 조회
     *
     * @LRDparam page integer|nullable 페이지 번호
     * @LRDparam per_page integer|nullable 페이지당 항목 수
     * @LRDparam search string|nullable 검색 조건
     * @LRDparam with string|nullable 포함할 관계
     * @LRDresponses 200|403|500
     *
     */
    public function index(Request $request)
    {
        return $this->indexQuery($request, Code::query());
    }

    /**
     * 코드 상세 조회
     *
     * @LRDparam search string|nullable 검색 조건
     * @LRDparam with string|nullable 포함할 관계
     * @LRDresponses 200|403|404|500
     */
    public function show(Request $request, string $id)
    {
        return $this->showQuery($id, $request);
    }
}
